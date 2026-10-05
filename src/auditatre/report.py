"""Relatório textual. Não publica CPF e não classifica conduta."""

from __future__ import annotations

import re

PROIBIDAS = ("fraude", "improbidade", "culpado", "culpada")
CPF_RE = re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}")
TELEFONE_RE = re.compile(r"\(?\d{2}\)?\s*\d{4,5}-\d{4}")
CEP_RE = re.compile(r"\b\d{5}-\d{3}\b")


def renderizar(inventario: list[dict[str, object]], matriz: dict[str, object], lacunas: list[dict[str, object]]) -> str:
    linhas = [
        "# Auditatre",
        "",
        "Cruzamento documental. Organizacao, ato e vinculo ficam separados.",
        "Cada fase fica no proprio ato. Campo vazio permanece vazio.",
        "CNPJ comum nao atribui pagamento a contrato.",
        "Apostila nao abre contrato novo. Atesto de um polo nao fecha os outros.",
        "Planilha permanece hipotese ate um PDF confirmar o mesmo valor.",
        "Sancao exige penalidade, destinatario e ato no documento. Citacao nao basta.",
        "O relatorio nao atribui responsabilidade.",
        "",
        "## Inventario",
        "",
    ]
    for item in inventario:
        linhas.append(
            f"- `{item['caminho']}` status={item['status']} tipo={item.get('tipo') or '-'} bytes={item['bytes']}"
        )
    organizacoes = matriz.get("organizacoes") or []
    atos = matriz.get("atos") or []
    vinculos = matriz.get("vinculos") or []
    assert isinstance(organizacoes, list) and isinstance(atos, list) and isinstance(vinculos, list)
    linhas.extend(["", "## Organizacoes", ""])
    if not organizacoes:
        linhas.append("Nenhuma organizacao.")
    for org in organizacoes:
        linhas.append(f"### {org['id']}")
        linhas.append(f"- CNPJ: {org['cnpj']}")
        razoes = org["razoes_sociais"] or ["vazio"]
        linhas.append(f"- Razoes: {', '.join(razoes)}")
        linhas.append("")
    linhas.extend(["## Atos", ""])
    if not atos:
        linhas.append("Nenhum ato.")
    for ato in atos:
        fases = ato["fases"]
        assert isinstance(fases, dict)
        linhas.append(f"### {ato['id']}")
        linhas.append(f"- Tipo: {ato['tipo_ato']}")
        linhas.append(f"- Unidade: {ato['orgao_unidade'] or 'ausente'}")
        linhas.append(f"- Exercicio: {ato['exercicio'] or 'ausente'}")
        linhas.append(f"- Identificador: {ato['identificador']}")
        linhas.append(f"- Apostila: {'sim' if ato['apostila'] else 'nao'}")
        for fase in ("contrato", "empenho", "liquidacao", "pagamento"):
            registros = fases[fase]
            if not registros:
                linhas.append(f"- {fase}: vazio")
                continue
            for registro in registros:
                linhas.append(f"- {fase}: {registro['valor']} em `{registro['documento']}`")
        sancoes = ato["sancoes"]
        if not sancoes:
            linhas.append("- Sancao: vazia")
        for sancao in sancoes:
            destinatario = sancao["destinatario"]["cnpj"]
            ato_sancao = sancao["ato"]["tipo"]
            linhas.append(f"- Sancao: {sancao['penalidade']} destinatario={destinatario} ato={ato_sancao} em `{sancao['documento']}`")
            for data in sancao.get("datas") or []:
                linhas.append(f"- Data documentada: {data['rotulo']} {data['valor']}")
            for alcance in sancao.get("alcances") or []:
                linhas.append(f"- Alcance documentado: {alcance['valor']}")
        for decisao in ato["decisoes"]:
            linhas.append(f"- Decisao: {decisao['tipo']} {decisao['identificador']} em `{decisao['documento']}`")
        for processo in ato["processos"]:
            linhas.append(f"- Processo: {processo['identificador']} em `{processo['documento']}`")
        for pessoa in ato["pessoas"]:
            linhas.append(f"- {pessoa['papel']}: {pessoa['nome']} em `{pessoa['documento']}`")
        linhas.append("")
    linhas.extend(["## Vinculos", ""])
    if not vinculos:
        linhas.append("Nenhum vinculo.")
    for vinculo in vinculos:
        linhas.append(
            f"- {vinculo['id']} {vinculo['estado']}: {vinculo['origem']['id']} -> {vinculo['destino']['id']}. {vinculo['motivo']}."
        )
    linhas.extend(["", "## Lacunas", ""])
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
