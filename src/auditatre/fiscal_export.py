"""Exporta para o importador do Fiscal TRE-PA só valores com fornecedor confirmado.

Cada valor de fase vira um registro com um único campo monetário: as fases não
se somam e o Fiscal lê os campos vazios como ausentes, não como zero. O que não
fecha (sem fornecedor, sem exercício, conflito) vai para lacunas_exportacao.
"""

from __future__ import annotations

import hashlib

from auditatre.crosswalk import FASES, _componentes

FORMATO = "auditatre-fiscal/1"
# Só este vínculo diz quem é o fornecedor; o de sanção liga o ato ao punido.
MOTIVO_FORNECEDOR = "pareamento de cnpj e contrato"
CAMPO_DA_FASE = {
    "contrato": ("contract", "contract_value"),
    "empenho": ("payment", "committed"),
    "liquidacao": ("payment", "accrued"),
    "pagamento": ("payment", "paid"),
}
CAMPOS_FISCAL = (
    "record_id", "kind", "year", "supplier", "supplier_id", "contract_id", "document_id",
    "date", "competence", "installment", "status", "committed", "accrued", "paid",
    "contract_value", "addendum_delta", "reported_amount", "aggregate_paid_amount",
    "object", "source_url", "source_page",
)


def _lacuna(ato_id: str, fase: str, motivo: str, documento: str | None = None) -> dict[str, object]:
    return {"ato": ato_id, "documento": documento, "fase": fase, "motivo": motivo, "valor": None}


def _ids_em_conflito(vinculos: list[dict[str, object]]) -> set[str]:
    ids: set[str] = set()
    for vinculo in vinculos:
        if vinculo["estado"] == "conflito":
            ids.add(str(vinculo["origem"]["id"]))  # type: ignore[index]
            ids.add(str(vinculo["destino"]["id"]))  # type: ignore[index]
    return ids


def _fornecedores(membros: list[dict[str, object]], vinculos: list[dict[str, object]]) -> set[str]:
    ids = {str(ato["id"]) for ato in membros}
    orgs: set[str] = set()
    for vinculo in vinculos:
        if vinculo["estado"] != "confirmado" or vinculo["motivo"] != MOTIVO_FORNECEDOR:
            continue
        origem, destino = vinculo["origem"], vinculo["destino"]
        assert isinstance(origem, dict) and isinstance(destino, dict)
        if origem["tipo"] == "ato" and destino["tipo"] == "organizacao" and str(origem["id"]) in ids:
            orgs.add(str(destino["id"]))
    return orgs


def _exercicio(ato: dict[str, object]) -> str | None:
    if ato["exercicio"]:
        return str(ato["exercicio"])
    exercicios = ato["exercicios"]
    assert isinstance(exercicios, list)
    return str(exercicios[0]) if len(exercicios) == 1 else None


def _contrato(membros: list[dict[str, object]]) -> str:
    contratos = sorted(
        {str(ato["identificador"]) for ato in membros if ato["tipo_ato"] == "contrato" and ato["constituido"]}
    )
    return contratos[0] if len(contratos) == 1 else ""


def _localizador(documento: str, span: dict[str, object], origem: dict[str, object]) -> str:
    partes = [f"documento:{documento}", f"sha256:{origem['sha256']}", f"span:{span['inicio']}-{span['fim']}"]
    drive = origem.get("drive")
    if isinstance(drive, list) and drive:
        partes.append("drive:" + ",".join(sorted({str(item["drive_id"]) for item in drive})))
    return " | ".join(partes)


def exportar(
    matriz: dict[str, list[dict[str, object]]], inventario: list[dict[str, object]]
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Devolve o arquivo de importação do Fiscal e as lacunas da exportação."""
    atos = {str(ato["id"]): ato for ato in matriz["atos"]}
    orgs = {str(org["id"]): org for org in matriz["organizacoes"]}
    vinculos = matriz["vinculos"]
    por_caminho = {str(item["caminho"]): item for item in inventario}
    conflitos = _ids_em_conflito(vinculos)
    cnpjs_do_documento: dict[str, set[str]] = {}
    for org_id, org in orgs.items():
        for documento in org["documentos"]:  # type: ignore[union-attr]
            cnpjs_do_documento.setdefault(str(documento), set()).add(org_id)
    registros: list[dict[str, object]] = []
    lacunas: list[dict[str, object]] = []

    for membros in _componentes(atos, vinculos).values():
        fornecedores = _fornecedores(membros, vinculos)
        contrato = _contrato(membros)
        for ato in sorted(membros, key=lambda item: str(item["id"])):
            ato_id = str(ato["id"])
            fases = ato["fases"]
            assert isinstance(fases, dict)
            if not any(fases[fase] for fase in FASES):
                continue
            exercicio = _exercicio(ato)
            if ato_id in conflitos:
                motivo = "ato com vinculo em conflito"
            elif not fornecedores:
                motivo = "sem fornecedor confirmado"
            elif len(fornecedores) > 1:
                motivo = "mais de um fornecedor confirmado"
            elif len(orgs[next(iter(fornecedores))]["razoes_sociais"]) != 1:  # type: ignore[arg-type]
                motivo = "fornecedor sem razao social unica"
            elif exercicio is None:
                motivo = "exercicio ausente ou ambiguo"
            else:
                motivo = None
            vistos: set[tuple[str, str, str]] = set()
            for fase in FASES:
                for valor in fases[fase]:
                    documento = str(valor["documento"])
                    # O conflito do documento explica melhor a ausência de fornecedor que ele mesmo causou.
                    if documento in conflitos:
                        lacunas.append(_lacuna(ato_id, fase, "documento com vinculo em conflito", documento))
                        continue
                    if motivo is not None:
                        lacunas.append(_lacuna(ato_id, fase, motivo, documento))
                        continue
                    # Pagamento que cita o contrato mas favorece outro CNPJ não herda o fornecedor do contrato.
                    citados = cnpjs_do_documento.get(documento, set())
                    if citados and not fornecedores & citados:
                        lacunas.append(_lacuna(ato_id, fase, "cnpj do documento diverge do fornecedor", documento))
                        continue
                    origem = por_caminho.get(documento)
                    if origem is None or not origem.get("sha256"):
                        lacunas.append(_lacuna(ato_id, fase, "documento sem sha256 no inventario", documento))
                        continue
                    # O mesmo valor citado duas vezes no mesmo documento é um fato só.
                    chave = (fase, documento, str(valor["valor"]))
                    if chave in vistos:
                        continue
                    vistos.add(chave)
                    org = orgs[next(iter(fornecedores))]
                    kind, campo = CAMPO_DA_FASE[fase]
                    span = valor["span"]
                    assert isinstance(span, dict)
                    semente = "|".join([ato_id, fase, str(origem["sha256"]), str(span["inicio"]), str(span["fim"])])
                    registro: dict[str, object] = {nome: None for nome in CAMPOS_FISCAL}
                    registro.update(
                        {
                            "record_id": "auditatre-" + hashlib.sha256(semente.encode()).hexdigest()[:20],
                            "kind": kind,
                            "year": exercicio,
                            "supplier": org["razoes_sociais"][0],  # type: ignore[index]
                            "supplier_id": org["cnpj"],
                            "contract_id": contrato,
                            "document_id": str(ato["identificador"]) if ato["tipo_ato"] == "empenho" else "",
                            campo: str(valor["valor"]),
                            "source_url": "",
                            "source_page": _localizador(documento, span, origem),
                        }
                    )
                    registros.append(registro)

    registros.sort(key=lambda item: str(item["record_id"]))
    lacunas.sort(key=lambda item: (str(item["ato"]), str(item["fase"]), str(item["documento"])))
    return {"formato": FORMATO, "records": registros}, lacunas
