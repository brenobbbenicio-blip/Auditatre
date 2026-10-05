import hashlib
import inspect
import io
import json
import zipfile
from pathlib import Path

import pytest

from auditatre.cli import main
from auditatre.extract import cnpj_valido, cpf_valido, extrair
from auditatre.run import executar
from auditatre.zipsafe import LimitesZip, abrir_zip
from tests.pdfutil import pdf_texto


def _cnpj(raiz: str = "112223330001") -> str:
    digitos = raiz
    assert len(digitos) == 12

    def dv(base: str, pesos: list[int]) -> str:
        total = sum(int(a) * b for a, b in zip(base, pesos))
        resto = total % 11
        return "0" if resto < 2 else str(11 - resto)

    primeiro = dv(digitos, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    segundo = dv(digitos + primeiro, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    completo = digitos + primeiro + segundo
    return f"{completo[:2]}.{completo[2:5]}.{completo[5:8]}/{completo[8:12]}-{completo[12:]}"


CNPJ = _cnpj()
CPF = "111.444.777-35"


def test_cnpj_e_cpf_validos():
    assert cnpj_valido(CNPJ)
    assert not cnpj_valido("11.222.333/0001-00")
    assert cpf_valido(CPF)
    assert not cpf_valido("111.444.777-00")


def test_zip_recusa_traversal_e_bomba_e_profundidade(tmp_path: Path):
    mau = tmp_path / "traversal.zip"
    with zipfile.ZipFile(mau, "w") as arquivo:
        arquivo.writestr("../segredo.txt", "nao")
    recusa = abrir_zip(mau.read_bytes(), "traversal.zip")
    assert recusa[0].status == "zip_recusado"
    assert recusa[0].motivo == "path traversal"

    bomba = tmp_path / "bomba.zip"
    with zipfile.ZipFile(bomba, "w", compression=zipfile.ZIP_DEFLATED) as arquivo:
        arquivo.writestr("zeros.bin", b"\0" * 200_000)
    recusa = abrir_zip(bomba.read_bytes(), "bomba.zip", limites=LimitesZip(max_ratio=20))
    assert recusa[0].motivo == "zip bomb"

    def aninhar(nivel: int, conteudo: bytes, nome: str) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as arquivo:
            arquivo.writestr(nome, conteudo)
        if nivel == 1:
            return buffer.getvalue()
        return aninhar(nivel - 1, buffer.getvalue(), "interno.zip")

    profundo = aninhar(4, b"sigiloso", "alvo.txt")
    membros = abrir_zip(profundo, "camada.zip")
    caminhos = [membro.caminho for membro in membros if membro.dados]
    assert not any(membro.dados == b"sigiloso" for membro in membros)
    assert any(membro.motivo == "profundidade" for membro in membros)
    assert all(".." not in caminho for caminho in caminhos)

    tres = aninhar(3, b"visivel", "alvo.txt")
    membros = abrir_zip(tres, "tres.zip")
    assert any(membro.dados == b"visivel" for membro in membros)


def test_dedup_pdf_sem_texto_e_arquivo_grande(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    pdf = pdf_texto(None)
    (inbox / "a.pdf").write_bytes(pdf)
    (inbox / "b.pdf").write_bytes(pdf)
    limite = len(pdf) + 10
    (inbox / "grande.bin").write_bytes(b"x" * (limite + 30))
    resultado = executar(inbox, tmp_path / "out", max_bytes=limite)
    status = {item["caminho"]: item["status"] for item in resultado["inventario"]}
    assert status["a.pdf"] == "sem_texto"
    assert status["b.pdf"] == "duplicado"
    assert status["grande.bin"] == "catalogado"
    assert not any(lacuna["motivo"] == "pdf sem texto" and lacuna["valor"] == 0 for lacuna in resultado["lacunas"])
    assert any(lacuna["motivo"] == "pdf sem texto" and lacuna["valor"] is None for lacuna in resultado["lacunas"])


def test_nao_soma_fases_nem_trata_apostila_como_contrato(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "contrato.txt").write_text(
        "\n".join(
            [
                "CONTRATO N 41/2025",
                f"CONTRATADO CNPJ {CNPJ} EMPRESA EXEMPLO LTDA.",
                "O valor global do contrato e de R$ 70.000,00.",
                "Nota de Empenho: 2025NE511.",
                "Polos de Maraba, Santarem e Belem.",
                "Atesto a execucao do polo Maraba.",
                "Rua das Flores 10 CEP 66015-902 telefone (91) 3346-8000.",
                "CPF ***.777.754-** nao deve sair.",
            ]
        ),
        encoding="utf-8",
    )
    (inbox / "empenho.txt").write_text(
        "\n".join(
            [
                "Nota de Empenho",
                "Ano Tipo Numero 2025 NE 000511",
                f"Favorecido Codigo Nome {CNPJ} 000 EMPRESA EXEMPLO LTDA",
                "Valor 15.500,00",
                "Valor Total 4.000,00",
                "Valor Total 11.500,00",
                "Ordenador de despesa: Rosiane Revelle dos Santos Martinelli",
                "Fiscal do contrato: Ana Paula Nogueira",
            ]
        ),
        encoding="utf-8",
    )
    (inbox / "apostila.txt").write_text(
        f"Termo de apostilamento do Contrato n 41/2025. CNPJ {CNPJ}. Valor da apostila R$ 1.000,00.\n",
        encoding="utf-8",
    )
    (inbox / "planilha.csv").write_text(
        "CNPJ,NE,Empenhado,Liquidado\n"
        f"{CNPJ},2025NE000511,\"R$ 15.500,00\",0\n",
        encoding="utf-8",
    )
    (inbox / "ceis.txt").write_text(f"CEIS\nFornecedor CNPJ {CNPJ} EMPRESA EXEMPLO LTDA.\n", encoding="utf-8")
    (inbox / "ata.txt").write_text(
        "Ata de reuniao.\nFiscal do contrato: Ana Paula Nogueira compareceu.\n",
        encoding="utf-8",
    )
    resultado = executar(inbox, tmp_path / "out")
    grupo = next(item for item in resultado["matriz"] if item["contrato"] == "41/2025")
    assert grupo["apostila"] is True
    assert [item["valor"] for item in grupo["fases"]["contrato"]] == ["70000.00"]
    assert [item["valor"] for item in grupo["fases"]["empenho"]] == ["15500.00"]
    assert grupo["fases"]["liquidacao"] == []
    assert grupo["fases"]["pagamento"] == []
    assert "31000.00" not in json.dumps(resultado["matriz"])
    assert "19500.00" not in json.dumps(resultado["matriz"])
    assert all(lacuna["valor"] is None for lacuna in resultado["lacunas"] if lacuna["fase"] in {"liquidacao", "pagamento"})
    assert "maraba" not in grupo["polos_em_aberto"]
    assert "santarem" in grupo["polos_em_aberto"]
    assert "belem" in grupo["polos_em_aberto"]
    assert grupo["sancao"]["cnpj"] == CNPJ
    assert any(pessoa["papel"] == "ordenador" for pessoa in grupo["pessoas"])
    hipotese = next(item for item in grupo["hipoteses"] if item["fase"] == "empenho")
    assert hipotese["confirmada"] is True
    assert not any(item["fase"] == "liquidacao" and item["valor"] in {"0", "0.00"} for item in grupo["hipoteses"])
    bruto = json.dumps(resultado, ensure_ascii=False) + resultado["relatorio"]
    assert "111.444.777-35" not in bruto
    assert "777.754" not in bruto
    assert "66015-902" not in bruto
    assert "3346-8000" not in bruto
    assert "fraude" not in resultado["relatorio"].lower()
    manifesto = json.loads((tmp_path / "out" / "manifesto.json").read_text(encoding="utf-8"))
    inventario = (tmp_path / "out" / "inventario.json").read_bytes()
    assert manifesto["saidas"]["inventario.json"]["sha256"] == hashlib.sha256(inventario).hexdigest()


def test_nome_igual_nao_preenche_sancao_e_planilha_sem_pdf(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "ata.txt").write_text(
        "Ata.\nFiscal do contrato: Ana Paula Nogueira.\n",
        encoding="utf-8",
    )
    (inbox / "so_planilha.csv").write_text(
        f"CNPJ,Contrato,Empenhado\n{CNPJ},41/2025,\"R$ 10,00\"\n",
        encoding="utf-8",
    )
    resultado = executar(inbox, tmp_path / "out")
    assert all(grupo["sancao"] is None for grupo in resultado["matriz"])
    planilha = next(grupo for grupo in resultado["matriz"] if grupo["cnpj"] == CNPJ)
    assert planilha["fases"]["empenho"] == []
    assert planilha["hipoteses"]
    assert planilha["hipoteses"][0]["confirmada"] is False
    assert any(lacuna["motivo"].startswith("planilha segue como hipotese") for lacuna in resultado["lacunas"])


def test_cpf_aberto_nao_sai_no_relatorio(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "folha_servidores.txt").write_text(
        f"Folha de pagamento dos servidores\nMARIA DAS DORES LIMA\nCPF {CPF}\n",
        encoding="utf-8",
    )
    resultado = executar(inbox, tmp_path / "out")
    assert CPF not in resultado["relatorio"]
    assert CPF not in json.dumps(resultado["matriz"])
    pessoa = resultado["matriz"][0]["pessoas"][0]
    assert pessoa["papel"] == "servidor_folha"
    assert pessoa["pessoa_ref"]


def test_achado_exige_span():
    with pytest.raises(ValueError):
        from auditatre.extract import Achado, Span

        Achado(tipo="ne", valor="2025NE000001", span=Span(0, 0, ""))


def test_cli_para_sem_inbox(tmp_path: Path):
    assert main(["--inbox", str(tmp_path / "ausente"), "--out", str(tmp_path / "out")]) == 2


def test_modulos_nao_acessam_rede():
    import auditatre.cli
    import auditatre.crosswalk
    import auditatre.extract
    import auditatre.leitura
    import auditatre.run
    import auditatre.zipsafe

    for modulo in (
        auditatre.cli,
        auditatre.crosswalk,
        auditatre.extract,
        auditatre.leitura,
        auditatre.run,
        auditatre.zipsafe,
    ):
        fonte = inspect.getsource(modulo)
        assert "urllib" not in fonte
        assert "requests" not in fonte
        assert "socket" not in fonte
        assert "httpx" not in fonte


def test_extractor_nao_cria_pessoa_sem_papel():
    doc = extrair(
        "nota.txt",
        "Nota de Empenho\nFavorecido Codigo Nome 11.222.333/0001-81 000 EMPRESA EXEMPLO LTDA\nGestor Financeiro sem nome na mesma linha\n",
    )
    assert not any(achado.tipo == "pessoa" for achado in doc.achados)
