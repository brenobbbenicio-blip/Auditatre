"""Regressões fictícias de vínculo e de sanção. Não usam corpus real."""

from pathlib import Path

from auditatre.run import executar
from tests.test_auditatre import _cnpj

CNPJ_A = _cnpj("112223330001")
CNPJ_B = _cnpj("223334440001")


def _executar(tmp_path: Path, arquivos: dict[str, str]) -> dict[str, object]:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    for nome, texto in arquivos.items():
        (inbox / nome).write_text(texto, encoding="utf-8")
    return executar(inbox, tmp_path / "out")


def _atos(resultado: dict[str, object], tipo: str, identificador: str) -> list[dict[str, object]]:
    return [
        ato
        for ato in resultado["matriz"]["atos"]
        if ato["tipo_ato"] == tipo and ato["identificador"] == identificador
    ]


def _confirmados_entre(resultado: dict[str, object], esquerda: str, direita: str) -> list[dict[str, object]]:
    alvo = {esquerda, direita}
    return [
        vinculo
        for vinculo in resultado["matriz"]["vinculos"]
        if vinculo["estado"] == "confirmado" and {vinculo["origem"]["id"], vinculo["destino"]["id"]} == alvo
    ]


def test_cnpj_comum_nao_atribui_pagamento_aos_contratos(tmp_path: Path):
    resultado = _executar(
        tmp_path,
        {
            "contrato_10.txt": "\n".join(
                [
                    "CONTRATO N 10/2024",
                    f"CONTRATADO CNPJ {CNPJ_A} EMPRESA ALFA LTDA.",
                    "O valor global do contrato e de R$ 1.000,00.",
                ]
            ),
            "contrato_11.txt": "\n".join(
                [
                    "CONTRATO N 11/2024",
                    f"CONTRATADO CNPJ {CNPJ_A} EMPRESA ALFA LTDA.",
                    "O valor global do contrato e de R$ 2.000,00.",
                ]
            ),
            "pagamento_solto.txt": "\n".join(
                [
                    "Ordem bancaria",
                    f"Favorecido CNPJ {CNPJ_A} EMPRESA ALFA LTDA.",
                    "Valor pago R$ 9.000,00.",
                ]
            ),
            "pagamento_citado.txt": "\n".join(
                [
                    "Ordem bancaria",
                    "Contrato n 10/2024.",
                    f"Favorecido CNPJ {CNPJ_A} EMPRESA ALFA LTDA.",
                    "Valor pago R$ 3.000,00.",
                ]
            ),
        },
    )
    contrato_10 = _atos(resultado, "contrato", "10/2024")[0]
    contrato_11 = _atos(resultado, "contrato", "11/2024")[0]
    solto = next(ato for ato in resultado["matriz"]["atos"] if ato["identificador"] == "pagamento_solto.txt")
    citado = next(ato for ato in resultado["matriz"]["atos"] if ato["identificador"] == "pagamento_citado.txt")
    assert [item["valor"] for item in solto["fases"]["pagamento"]] == ["9000.00"]
    assert [item["valor"] for item in citado["fases"]["pagamento"]] == ["3000.00"]
    assert contrato_10["fases"]["pagamento"] == []
    assert contrato_11["fases"]["pagamento"] == []
    assert _confirmados_entre(resultado, solto["id"], contrato_10["id"]) == []
    assert _confirmados_entre(resultado, solto["id"], contrato_11["id"]) == []
    assert _confirmados_entre(resultado, citado["id"], contrato_11["id"]) == []
    assert _confirmados_entre(resultado, citado["id"], contrato_10["id"])
    assert any(
        vinculo["estado"] == "candidato" and vinculo["motivo"] == "cnpj comum sem referencia ao ato"
        for vinculo in resultado["matriz"]["vinculos"]
    )


def test_ne_sem_referencia_nao_entra_no_unico_contrato(tmp_path: Path):
    resultado = _executar(
        tmp_path,
        {
            "contrato.txt": "\n".join(
                [
                    "CONTRATO N 7/2023",
                    f"CONTRATADO CNPJ {CNPJ_A} EMPRESA ALFA LTDA.",
                    "O valor global do contrato e de R$ 5.000,00.",
                ]
            ),
            "empenho.txt": "\n".join(
                [
                    "Nota de Empenho",
                    "Ano Tipo Numero 2023 NE 000999",
                    f"Favorecido Codigo Nome {CNPJ_A} 000 EMPRESA ALFA LTDA",
                    "Valor R$ 800,00",
                ]
            ),
        },
    )
    contrato = _atos(resultado, "contrato", "7/2023")[0]
    empenho = _atos(resultado, "empenho", "2023NE000999")[0]
    assert [item["valor"] for item in empenho["fases"]["empenho"]] == ["800.00"]
    assert contrato["fases"]["empenho"] == []
    assert _confirmados_entre(resultado, contrato["id"], empenho["id"]) == []


def test_contratos_de_unidades_distintas_nao_compartilham_ato(tmp_path: Path):
    resultado = _executar(
        tmp_path,
        {
            "contrato_a.txt": "\n".join(
                [
                    "CONTRATO N 10/2024",
                    "Unidade gestora: 150001",
                    f"CONTRATADO CNPJ {CNPJ_A} EMPRESA ALFA LTDA.",
                    "O valor global do contrato e de R$ 1.000,00.",
                ]
            ),
            "contrato_b.txt": "\n".join(
                [
                    "CONTRATO N 10/2024",
                    "Unidade gestora: 150002",
                    f"CONTRATADO CNPJ {CNPJ_A} EMPRESA ALFA LTDA.",
                    "O valor global do contrato e de R$ 2.000,00.",
                ]
            ),
        },
    )
    atos = _atos(resultado, "contrato", "10/2024")
    assert len(atos) == 2
    por_unidade = {ato["orgao_unidade"]: ato for ato in atos}
    assert set(por_unidade) == {"150001", "150002"}
    assert [item["valor"] for item in por_unidade["150001"]["fases"]["contrato"]] == ["1000.00"]
    assert [item["valor"] for item in por_unidade["150002"]["fases"]["contrato"]] == ["2000.00"]
    assert any(
        vinculo["estado"] == "conflito" and {vinculo["origem"]["id"], vinculo["destino"]["id"]} == {atos[0]["id"], atos[1]["id"]}
        for vinculo in resultado["matriz"]["vinculos"]
    )


def test_varios_cnpjs_e_contratos_nao_geram_pares_confirmados(tmp_path: Path):
    resultado = _executar(
        tmp_path,
        {
            "relacao.txt": "\n".join(
                [
                    f"CNPJ {CNPJ_A} EMPRESA ALFA LTDA.",
                    f"CNPJ {CNPJ_B} EMPRESA BETA LTDA.",
                    "Contrato n 1/2022.",
                    "Contrato n 2/2022.",
                ]
            )
        },
    )
    orgs = {org["id"] for org in resultado["matriz"]["organizacoes"]}
    assert orgs == {f"org:{CNPJ_A}", f"org:{CNPJ_B}"}
    contratos = [ato for ato in resultado["matriz"]["atos"] if ato["tipo_ato"] == "contrato"]
    assert {ato["identificador"] for ato in contratos} == {"1/2022", "2/2022"}
    confirmados = [
        vinculo
        for vinculo in resultado["matriz"]["vinculos"]
        if vinculo["estado"] == "confirmado"
        and {vinculo["origem"]["tipo"], vinculo["destino"]["tipo"]} == {"ato", "organizacao"}
    ]
    assert confirmados == []
    assert any(vinculo["estado"] == "conflito" for vinculo in resultado["matriz"]["vinculos"])


def test_sentenca_sem_penalidade_nao_vira_sancao(tmp_path: Path):
    resultado = _executar(
        tmp_path,
        {
            "sentenca_citacao.txt": "\n".join(
                [
                    "Sentenca",
                    "Processo 0001234-55.2020.8.14.0001",
                    f"A EMPRESA ALFA LTDA, CNPJ {CNPJ_A}, foi citada como testemunha.",
                ]
            )
        },
    )
    ato = next(item for item in resultado["matriz"]["atos"] if item["tipo_ato"] == "sentenca")
    assert ato["sancoes"] == []
    assert ato["decisoes"]
    assert ato["decisoes"][0]["tipo"] == "sentenca"
    assert any(processo["especie"] == "processo" for processo in ato["processos"])
    assert all(not item["sancoes"] for item in resultado["matriz"]["atos"])


def test_acordao_que_so_cita_empresa_nao_vincula_sancao(tmp_path: Path):
    resultado = _executar(
        tmp_path,
        {
            "contrato.txt": "\n".join(
                [
                    "CONTRATO N 8/2021",
                    f"CONTRATADO CNPJ {CNPJ_B} EMPRESA BETA LTDA.",
                    "O valor global do contrato e de R$ 4.000,00.",
                ]
            ),
            "acordao_citacao.txt": "\n".join(
                [
                    "Acordao 55/2021",
                    f"A empresa EMPRESA BETA LTDA, CNPJ {CNPJ_B}, foi citada na fundamentacao.",
                ]
            ),
        },
    )
    acordao = next(item for item in resultado["matriz"]["atos"] if item["tipo_ato"] == "acordao")
    contrato = _atos(resultado, "contrato", "8/2021")[0]
    assert acordao["sancoes"] == []
    assert acordao["decisoes"][0]["identificador"] == "55/2021"
    assert contrato["sancoes"] == []
    assert _confirmados_entre(resultado, acordao["id"], contrato["id"]) == []


def test_sancoes_multiplas_preservam_data_e_alcance_documentados(tmp_path: Path):
    resultado = _executar(
        tmp_path,
        {
            "ceis_duas.txt": "\n".join(
                [
                    "CEIS",
                    f"Destinatario CNPJ {CNPJ_A} EMPRESA ALFA LTDA.",
                    "Penalidade: advertencia.",
                    "Penalidade: multa.",
                ]
            ),
            "cnep_outra.txt": "\n".join(
                [
                    "CNEP",
                    f"Destinatario CNPJ {CNPJ_A} EMPRESA ALFA LTDA.",
                    "Penalidade: declaracao de inidoneidade.",
                    "Data de inicio: 01/02/2020",
                    "Data de fim: 03/04/2021",
                    "Alcance: esfera federal",
                ]
            ),
            "ceis_sem_penalidade.txt": f"CEIS\nFornecedor CNPJ {CNPJ_A} EMPRESA ALFA LTDA.\n",
        },
    )
    sancoes = [sancao for ato in resultado["matriz"]["atos"] for sancao in ato["sancoes"]]
    penalidades = [sancao["penalidade"] for sancao in sancoes]
    assert penalidades.count("advertencia") == 1
    assert penalidades.count("multa") == 1
    assert penalidades.count("declaracao de inidoneidade") == 1
    assert "ceis_sem_penalidade.txt" not in {sancao["documento"] for sancao in sancoes}
    duas = next(ato for ato in resultado["matriz"]["atos"] if ato["identificador"] == "ceis_duas.txt")
    assert [sancao["penalidade"] for sancao in duas["sancoes"]] == ["advertencia", "multa"]
    assert all(sancao["datas"] == [] and sancao["alcances"] == [] for sancao in duas["sancoes"])
    outra = next(sancao for sancao in sancoes if sancao["penalidade"] == "declaracao de inidoneidade")
    assert outra["destinatario"]["cnpj"] == CNPJ_A
    assert outra["ato"]["tipo"] == "cnep"
    assert [item["valor"] for item in outra["datas"]] == ["01/02/2020", "03/04/2021"]
    assert [item["rotulo"] for item in outra["datas"]] == ["data de inicio", "data de fim"]
    assert [item["valor"] for item in outra["alcances"]] == ["esfera federal"]
