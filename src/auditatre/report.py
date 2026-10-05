"""Relatório textual. Não publica CPF e não classifica conduta."""

from __future__ import annotations

import re

PROIBIDAS = ("fraude", "improbidade", "culpado", "culpada")
CPF_RE = re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}")
TELEFONE_RE = re.compile(r"\(?\d{2}\)?\s*\d{4,5}-\d{4}")
CEP_RE = re.compile(r"\b\d{5}-\d{3}\b")


def renderizar(inventario: list[dict[str, object]], matriz: list[dict[str, object]], lacunas: list[dict[str, object]]) -> str:
    linhas = [
        "# Auditatre",
        "",
        "Cruzamento documental. Cada fase fica no proprio registro. Campo vazio permanece vazio.",
        "Apostila nao abre contrato novo. Atesto de um polo nao fecha os outros.",
        "Planilha permanece hipotese ate um PDF confirmar o mesmo valor.",
        "Sancao so aparece quando o corpus tem CEIS, CNEP, acordao ou sentenca com span.",
        "",
        "## Inventario",
        "",
    ]
    for item in inventario:
        linhas.append(
            f"- `{item['caminho']}` status={item['status']} tipo={item.get('tipo') or '-'} bytes={item['bytes']}"
        )
    linhas.extend(["", "## Matriz", ""])
    if not matriz:
        linhas.append("Nenhum grupo.")
    for grupo in matriz:
        fases = grupo["fases"]
        assert isinstance(fases, dict)
        linhas.append(f"### {grupo['id']}")
        linhas.append(f"- CNPJ: {grupo['cnpj'] or 'vazio'}")
        linhas.append(f"- Contrato: {grupo['contrato'] or 'vazio'}")
        linhas.append(f"- Apostila: {'sim' if grupo['apostila'] else 'nao'}")
        for fase in ("contrato", "empenho", "liquidacao", "pagamento"):
            registros = fases[fase]
            if not registros:
                linhas.append(f"- {fase}: vazio")
                continue
            for registro in registros:
                linhas.append(f"- {fase}: {registro['valor']} em `{registro['documento']}`")
        sancao = grupo["sancao"]
        linhas.append(f"- Sancao: {sancao['documento'] if isinstance(sancao, dict) else 'vazia'}")
        for pessoa in grupo["pessoas"]:  # type: ignore[union-attr]
            linhas.append(f"- {pessoa['papel']}: {pessoa['nome']} em `{pessoa['documento']}`")
        linhas.append("")
    linhas.extend(["## Lacunas", ""])
    if not lacunas:
        linhas.append("Nenhuma lacuna de fase.")
    for lacuna in lacunas:
        polo = f" polo={lacuna['polo']}" if lacuna.get("polo") else ""
        linhas.append(f"- {lacuna['grupo']}: {lacuna['fase']} valor=vazio{polo}. {lacuna['motivo']}.")
    linhas.append("")
    texto = "\n".join(linhas)
    _recusar(texto)
    return texto


def _recusar(texto: str) -> None:
    base = texto.lower()
    for palavra in PROIBIDAS:
        if palavra in base:
            raise ValueError(f"relatorio contem termo proibido: {palavra}")
    if CPF_RE.search(texto) or TELEFONE_RE.search(texto) or CEP_RE.search(texto):
        raise ValueError("relatorio contem CPF, telefone ou CEP")
