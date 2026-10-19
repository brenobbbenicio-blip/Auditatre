"""Exportação para o importador do Fiscal TRE-PA. Corpus fictício, sem rede."""

import hashlib
import json
import re
from pathlib import Path

from auditatre.fiscal_export import CAMPOS_FISCAL, FORMATO, exportar
from auditatre.run import executar
from tests.test_auditatre import _cnpj

CNPJ_A = _cnpj("112223330001")
CNPJ_B = _cnpj("223334440001")
# Espelho das regras de normalize_rows do Fiscal (audit_core.py) que o exportador precisa cumprir.
OBRIGATORIO = {"contract": "contract_value", "payment": ("committed", "accrued", "paid")}
DINHEIRO = ("committed", "accrued", "paid", "contract_value", "addendum_delta", "reported_amount", "aggregate_paid_amount")

CONTRATO = f"CONTRATO N 10/2024\nCONTRATADO CNPJ {CNPJ_A} EMPRESA ALFA LTDA.\nO valor global do contrato e de R$ 1.000,00."
EMPENHO = f"Nota de empenho 2024NE000123\nContrato n 10/2024.\nFavorecido CNPJ {CNPJ_A} EMPRESA ALFA LTDA.\nValor R$ 1.000,00."
PAGAMENTO = f"Ordem bancaria\nContrato n 10/2024.\nFavorecido CNPJ {CNPJ_A} EMPRESA ALFA LTDA.\nValor pago R$ 300,00."


def _executar(tmp_path: Path, arquivos: dict[str, str]) -> dict[str, object]:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    for nome, texto in arquivos.items():
        (inbox / nome).write_text(texto, encoding="utf-8")
    return executar(inbox, tmp_path / "out")


def _registros(resultado: dict[str, object]) -> list[dict[str, object]]:
    return resultado["fiscal_import"]["records"]  # type: ignore[index]


def test_cada_fase_vira_um_registro_com_um_unico_valor(tmp_path: Path):
    resultado = _executar(tmp_path, {"contrato.txt": CONTRATO, "empenho.txt": EMPENHO, "pagamento.txt": PAGAMENTO})
    por_kind = []
    for registro in _registros(resultado):
        campo = next(nome for nome in DINHEIRO if registro[nome] is not None)
        por_kind.append((registro["kind"], campo, registro[campo]))
    assert sorted(por_kind) == [
        ("contract", "contract_value", "1000.00"),
        ("payment", "committed", "1000.00"),
        ("payment", "paid", "300.00"),
    ]
    for registro in _registros(resultado):
        assert sum(registro[campo] is not None for campo in DINHEIRO) == 1
        assert registro["supplier"] == "EMPRESA ALFA LTDA"
        assert registro["supplier_id"] == CNPJ_A
        assert registro["contract_id"] == "10/2024"
        assert registro["year"] == "2024"
    assert resultado["lacunas_exportacao"] == []


def test_registro_cumpre_o_contrato_do_importador_do_fiscal(tmp_path: Path):
    resultado = _executar(tmp_path, {"contrato.txt": CONTRATO, "empenho.txt": EMPENHO, "pagamento.txt": PAGAMENTO})
    arquivo = json.loads((tmp_path / "out" / "fiscal_import.json").read_text(encoding="utf-8"))
    assert arquivo["formato"] == FORMATO
    # O Fiscal recusa JSON com mais de uma lista de registros.
    assert [chave for chave, valor in arquivo.items() if isinstance(valor, list)] == ["records"]
    ids = [registro["record_id"] for registro in arquivo["records"]]
    assert len(ids) == len(set(ids))
    for registro in arquivo["records"]:
        assert tuple(sorted(registro)) == tuple(sorted(CAMPOS_FISCAL))
        assert all(not isinstance(valor, (dict, list, bool)) for valor in registro.values())
        assert re.fullmatch(r"\d{4}", registro["year"]) and 2000 <= int(registro["year"]) <= 2100
        assert registro["supplier"]
        exigidos = OBRIGATORIO[registro["kind"]]
        exigidos = exigidos if isinstance(exigidos, tuple) else (exigidos,)
        assert any(registro[campo] is not None for campo in exigidos)
        for campo in DINHEIRO:
            assert registro[campo] is None or re.fullmatch(r"\d+\.\d{2}", registro[campo])
        assert registro["source_url"] == ""
    inventario = {item["caminho"]: item["sha256"] for item in resultado["inventario"]}
    for registro in arquivo["records"]:
        documento = re.search(r"documento:(\S+)", registro["source_page"]).group(1)
        assert f"sha256:{inventario[documento]}" in registro["source_page"]
        assert re.search(r"span:\d+-\d+", registro["source_page"])


def test_record_id_e_deterministico(tmp_path: Path):
    arquivos = {"contrato.txt": CONTRATO, "pagamento.txt": PAGAMENTO}
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    primeiro = _executar(tmp_path / "a", arquivos)
    segundo = _executar(tmp_path / "b", arquivos)
    assert [r["record_id"] for r in _registros(primeiro)] == [r["record_id"] for r in _registros(segundo)]


def test_pagamento_sem_contrato_vira_lacuna_e_nao_registro(tmp_path: Path):
    resultado = _executar(
        tmp_path,
        {"pagamento_solto.txt": f"Ordem bancaria\nFavorecido CNPJ {CNPJ_A} EMPRESA ALFA LTDA.\nValor pago R$ 9.000,00."},
    )
    assert _registros(resultado) == []
    assert [(item["fase"], item["motivo"]) for item in resultado["lacunas_exportacao"]] == [
        ("pagamento", "sem fornecedor confirmado")
    ]


def test_documento_com_dois_cnpjs_sem_par_nao_exporta(tmp_path: Path):
    resultado = _executar(
        tmp_path,
        {
            "contrato.txt": "\n".join(
                [
                    "CONTRATO N 10/2024",
                    f"Contrato n 10/2024 CNPJ {CNPJ_A} EMPRESA ALFA LTDA.",
                    f"Contrato n 10/2024 CNPJ {CNPJ_B} EMPRESA BETA LTDA.",
                    "O valor global do contrato e de R$ 1.000,00.",
                ]
            )
        },
    )
    assert _registros(resultado) == []
    assert {item["motivo"] for item in resultado["lacunas_exportacao"]} == {"documento com vinculo em conflito"}


def test_pagamento_a_outro_cnpj_nao_herda_fornecedor_do_contrato(tmp_path: Path):
    outro = f"Ordem bancaria\nContrato n 10/2024.\nFavorecido CNPJ {CNPJ_B} EMPRESA BETA LTDA.\nValor pago R$ 300,00."
    resultado = _executar(tmp_path, {"contrato.txt": CONTRATO, "pagamento.txt": outro})
    assert [registro["kind"] for registro in _registros(resultado)] == ["contract"]
    assert [(item["fase"], item["motivo"]) for item in resultado["lacunas_exportacao"]] == [
        ("pagamento", "cnpj do documento diverge do fornecedor")
    ]


def test_planilha_sem_pdf_nao_e_exportada(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "so_planilha.csv").write_text(f"CNPJ,Contrato,Empenhado\n{CNPJ_A},41/2025,\"R$ 10,00\"\n", encoding="utf-8")
    resultado = executar(inbox, tmp_path / "out")
    assert _registros(resultado) == []


def test_manifesto_cobre_as_saidas_da_exportacao(tmp_path: Path):
    _executar(tmp_path, {"contrato.txt": CONTRATO})
    saida = tmp_path / "out"
    manifesto = json.loads((saida / "manifesto.json").read_text(encoding="utf-8"))
    for nome in ("fiscal_import.json", "lacunas_exportacao.json"):
        assert manifesto["saidas"][nome]["sha256"] == hashlib.sha256((saida / nome).read_bytes()).hexdigest()


def _matriz_com_sancao() -> dict[str, list[dict[str, object]]]:
    ato_id = "ato:pagamento|ug:ausente|exercicio:2024|id:ob.txt"
    ato = {
        "id": ato_id, "tipo_ato": "pagamento", "exercicio": "2024", "exercicios": ["2024"], "identificador": "ob.txt",
        "constituido": True,
        "fases": {"contrato": [], "empenho": [], "liquidacao": [],
                  "pagamento": [{"valor": "300.00", "documento": "ob.txt", "span": {"inicio": 1, "fim": 7, "trecho": "300,00"}}]},
    }
    org = {"id": f"org:{CNPJ_A}", "cnpj": CNPJ_A, "razoes_sociais": ["EMPRESA ALFA LTDA"], "documentos": ["ob.txt"]}
    vinculo = {"origem": {"tipo": "ato", "id": ato_id}, "destino": {"tipo": "organizacao", "id": org["id"]},
               "estado": "confirmado", "motivo": "destinatario da penalidade documentada"}
    return {"atos": [ato], "organizacoes": [org], "vinculos": [vinculo]}


def test_vinculo_de_sancao_nao_faz_do_punido_fornecedor():
    fiscal, lacunas = exportar(_matriz_com_sancao(), [{"caminho": "ob.txt", "sha256": "0" * 64}])
    assert fiscal["records"] == []
    assert [item["motivo"] for item in lacunas] == ["sem fornecedor confirmado"]


def test_vinculo_em_conflito_bloqueia_o_ato():
    matriz = _matriz_com_sancao()
    ato_id = matriz["atos"][0]["id"]
    matriz["vinculos"] = [
        {"origem": {"tipo": "ato", "id": ato_id}, "destino": {"tipo": "organizacao", "id": f"org:{CNPJ_A}"},
         "estado": "confirmado", "motivo": "pareamento de cnpj e contrato"},
        {"origem": {"tipo": "ato", "id": ato_id}, "destino": {"tipo": "ato", "id": "ato:outro"},
         "estado": "conflito", "motivo": "contexto de unidade divergente"},
    ]
    fiscal, lacunas = exportar(matriz, [{"caminho": "ob.txt", "sha256": "0" * 64}])
    assert fiscal["records"] == []
    assert [item["motivo"] for item in lacunas] == ["ato com vinculo em conflito"]


def test_dois_fornecedores_confirmados_nao_exporta():
    matriz = _matriz_com_sancao()
    ato_id = matriz["atos"][0]["id"]
    matriz["organizacoes"].append({"id": f"org:{CNPJ_B}", "cnpj": CNPJ_B, "razoes_sociais": ["EMPRESA BETA LTDA"],
                                  "documentos": ["ob.txt"]})
    matriz["vinculos"] = [
        {"origem": {"tipo": "ato", "id": ato_id}, "destino": {"tipo": "organizacao", "id": f"org:{cnpj}"},
         "estado": "confirmado", "motivo": "pareamento de cnpj e contrato"}
        for cnpj in (CNPJ_A, CNPJ_B)
    ]
    fiscal, lacunas = exportar(matriz, [{"caminho": "ob.txt", "sha256": "0" * 64}])
    assert fiscal["records"] == []
    assert [item["motivo"] for item in lacunas] == ["mais de um fornecedor confirmado"]


def test_razao_social_nao_comeca_dentro_do_cnpj(tmp_path: Path):
    resultado = _executar(tmp_path, {"contrato.txt": CONTRATO})
    org = next(item for item in resultado["matriz"]["organizacoes"] if item["cnpj"] == CNPJ_A)
    assert org["razoes_sociais"] == ["EMPRESA ALFA LTDA"]
