"""Cruza chaves públicas sem somar fases e sem ligar nome a sanção."""

from __future__ import annotations

from auditatre.extract import Achado, Documento

FASES = ("contrato", "empenho", "liquidacao", "pagamento")
VALOR_DA_FASE = {
    "valor_contrato": "contrato",
    "valor_empenho": "empenho",
    "valor_liquidacao": "liquidacao",
    "valor_pagamento": "pagamento",
}
HIPOTESE_DA_FASE = {
    "hipotese_contrato": "contrato",
    "hipotese_empenho": "empenho",
    "hipotese_liquidacao": "liquidacao",
    "hipotese_pagamento": "pagamento",
    "hipotese_valor": "valor",
}
ORDEM = {
    "contrato": 0,
    "apostila": 1,
    "ata": 2,
    "empenho": 3,
    "liquidacao": 4,
    "pagamento": 5,
    "diaria": 6,
    "prestacao": 7,
    "folha": 8,
    "remuneracao": 8,
    "sancao": 9,
    "acordao": 9,
    "sentenca": 9,
    "certidao": 9,
}


def _span(achado: Achado) -> dict[str, object]:
    return {"inicio": achado.span.inicio, "fim": achado.span.fim, "trecho": achado.span.trecho}


def _novo(gid: str) -> dict[str, object]:
    return {
        "id": gid,
        "cnpj": None,
        "razao_social": [],
        "sei": [],
        "contrato": None,
        "nes": [],
        "apostila": False,
        "fases": {fase: [] for fase in FASES},
        "itens": [],
        "hipoteses": [],
        "pessoas": [],
        "sancao": None,
        "atos": [],
        "unidades": [],
        "exercicios": [],
        "polos_em_aberto": [],
        "documentos": [],
    }


def _valores(doc: Documento, tipo: str) -> list[str]:
    return [achado.valor for achado in doc.achados if achado.tipo == tipo and achado.valor]


def _grupo_id(cnpj: str | None, contrato: str | None, ne: str | None, sei: str | None, caminho: str) -> str:
    if cnpj and contrato:
        return f"cnpj:{cnpj}|contrato:{contrato}"
    if contrato:
        return f"contrato:{contrato}"
    if cnpj and ne:
        return f"cnpj:{cnpj}|ne:{ne}"
    if ne:
        return f"ne:{ne}"
    if cnpj:
        return f"cnpj:{cnpj}"
    if sei:
        return f"sei:{sei}"
    return f"doc:{caminho}"


def _anexar_lista(destino: list[str], valores: list[str]) -> None:
    for valor in valores:
        if valor not in destino:
            destino.append(valor)


def _registrar_comum(grupo: dict[str, object], doc: Documento) -> None:
    documentos = grupo["documentos"]
    assert isinstance(documentos, list)
    if doc.caminho not in documentos:
        documentos.append(doc.caminho)
    _anexar_lista(grupo["razao_social"], _valores(doc, "razao_social"))  # type: ignore[arg-type]
    _anexar_lista(grupo["sei"], _valores(doc, "sei"))  # type: ignore[arg-type]
    _anexar_lista(grupo["nes"], _valores(doc, "ne"))  # type: ignore[arg-type]
    _anexar_lista(grupo["unidades"], _valores(doc, "unidade"))  # type: ignore[arg-type]
    _anexar_lista(grupo["exercicios"], _valores(doc, "exercicio"))  # type: ignore[arg-type]
    for achado in doc.achados:
        if achado.tipo == "ne" and achado.valor and achado.valor[0:4].isdigit():
            _anexar_lista(grupo["exercicios"], [achado.valor[0:4]])  # type: ignore[arg-type]
        if achado.tipo in {"contrato", "apostila_de"} and achado.valor and "/" in achado.valor:
            _anexar_lista(grupo["exercicios"], [achado.valor.split("/")[1]])  # type: ignore[arg-type]
        if achado.tipo == "pessoa" and achado.valor and achado.papel:
            pessoas = grupo["pessoas"]
            assert isinstance(pessoas, list)
            registro = {
                "nome": achado.valor,
                "papel": achado.papel,
                "documento": doc.caminho,
                "pessoa_ref": achado.pessoa_ref,
                "span": _span(achado),
            }
            if registro not in pessoas:
                pessoas.append(registro)
        if achado.tipo == "valor_item" and achado.valor:
            itens = grupo["itens"]
            assert isinstance(itens, list)
            itens.append({"valor": achado.valor, "documento": doc.caminho, "span": _span(achado)})
        if achado.tipo == "polo_em_aberto" and achado.valor:
            _anexar_lista(grupo["polos_em_aberto"], [achado.valor])  # type: ignore[arg-type]


def _registrar_fase(grupo: dict[str, object], doc: Documento) -> None:
    fases = grupo["fases"]
    assert isinstance(fases, dict)
    for achado in doc.achados:
        fase = VALOR_DA_FASE.get(achado.tipo)
        if not fase or not achado.valor or achado.hipotese:
            continue
        if fase == "contrato" and doc.tipo != "contrato":
            continue
        if fase == "empenho" and doc.tipo != "empenho":
            continue
        if fase == "liquidacao" and doc.tipo != "liquidacao":
            continue
        if fase == "pagamento" and doc.tipo != "pagamento":
            continue
        fases[fase].append({"valor": achado.valor, "documento": doc.caminho, "span": _span(achado)})
    if doc.tipo in {"sancao", "acordao", "sentenca", "certidao"}:
        atos = grupo["atos"]
        assert isinstance(atos, list)
        atos.append({"tipo": doc.tipo, "documento": doc.caminho})
    for achado in doc.achados:
        if achado.tipo == "sancao" and achado.valor and grupo["cnpj"] in {None, achado.valor}:
            if grupo["cnpj"] is None or grupo["cnpj"] == achado.valor:
                grupo["sancao"] = {
                    "cnpj": achado.valor,
                    "documento": doc.caminho,
                    "span": _span(achado),
                }


def _encontrar_grupo(grupos: dict[str, dict[str, object]], doc: Documento) -> list[dict[str, object]]:
    cnpjs = _valores(doc, "cnpj_fornecedor")
    contratos = _valores(doc, "contrato") or _valores(doc, "apostila_de")
    nes = _valores(doc, "ne")
    seis = _valores(doc, "sei")
    achados: list[dict[str, object]] = []
    if contratos:
        chaves = cnpjs or [None]
        for cnpj in chaves:
            for contrato in contratos:
                gid = _grupo_id(cnpj, contrato, None, None, doc.caminho)
                grupo = grupos.setdefault(gid, _novo(gid))
                grupo["cnpj"] = cnpj or grupo["cnpj"]
                grupo["contrato"] = contrato
                achados.append(grupo)
        return achados
    if nes:
        for ne in nes:
            encaixados = [
                grupo
                for grupo in grupos.values()
                if ne in grupo["nes"] and (not cnpjs or grupo["cnpj"] in cnpjs or grupo["cnpj"] is None)
            ]
            if encaixados:
                achados.extend(encaixados)
                continue
            mesmo_cnpj = [grupo for grupo in grupos.values() if cnpjs and grupo["cnpj"] in cnpjs and grupo["contrato"]]
            if len(mesmo_cnpj) == 1:
                achados.append(mesmo_cnpj[0])
                continue
            cnpj = cnpjs[0] if cnpjs else None
            gid = _grupo_id(cnpj, None, ne, None, doc.caminho)
            grupo = grupos.setdefault(gid, _novo(gid))
            grupo["cnpj"] = cnpj or grupo["cnpj"]
            achados.append(grupo)
        return achados
    if cnpjs:
        existentes = [grupo for grupo in grupos.values() if grupo["cnpj"] in cnpjs]
        if existentes and doc.tipo in {"sancao", "acordao", "sentenca", "certidao", "planilha", "empenho", "liquidacao", "pagamento"}:
            return existentes
        for cnpj in cnpjs:
            gid = _grupo_id(cnpj, None, None, None, doc.caminho)
            grupo = grupos.setdefault(gid, _novo(gid))
            grupo["cnpj"] = cnpj
            achados.append(grupo)
        return achados
    if seis:
        gid = _grupo_id(None, None, None, seis[0], doc.caminho)
        grupo = grupos.setdefault(gid, _novo(gid))
        achados.append(grupo)
        return achados
    gid = _grupo_id(None, None, None, None, doc.caminho)
    achados.append(grupos.setdefault(gid, _novo(gid)))
    return achados


def _anexar_hipotese(grupos: dict[str, dict[str, object]], doc: Documento) -> None:
    alvos = _encontrar_grupo(grupos, doc)
    if not any(doc.caminho in grupo["documentos"] or grupo["id"].startswith("doc:") for grupo in alvos):
        if not _valores(doc, "cnpj_fornecedor") and not _valores(doc, "contrato") and not _valores(doc, "ne"):
            alvos = _encontrar_grupo(grupos, doc)
    for grupo in alvos:
        _registrar_comum(grupo, doc)
        for achado in doc.achados:
            fase = HIPOTESE_DA_FASE.get(achado.tipo)
            if not fase or not achado.valor:
                continue
            fases = grupo["fases"]
            assert isinstance(fases, dict)
            confirmada = any(item["valor"] == achado.valor for item in fases.get(fase, []))
            grupo["hipoteses"].append(  # type: ignore[union-attr]
                {
                    "fase": fase,
                    "valor": achado.valor,
                    "documento": doc.caminho,
                    "confirmada": confirmada,
                    "span": _span(achado),
                }
            )


def cruzar(documentos: list[Documento]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    grupos: dict[str, dict[str, object]] = {}
    primarios = [doc for doc in documentos if doc.tipo != "planilha" and not doc.hipotese]
    hipoteses = [doc for doc in documentos if doc.tipo == "planilha" or doc.hipotese]
    for doc in sorted(primarios, key=lambda item: (ORDEM.get(item.tipo, 50), item.caminho)):
        if doc.tipo == "apostila":
            for grupo in _encontrar_grupo(grupos, doc):
                grupo["apostila"] = True
                _registrar_comum(grupo, doc)
            continue
        for grupo in _encontrar_grupo(grupos, doc):
            _registrar_comum(grupo, doc)
            _registrar_fase(grupo, doc)
    for doc in sorted(hipoteses, key=lambda item: item.caminho):
        _anexar_hipotese(grupos, doc)
    matriz = sorted(grupos.values(), key=lambda grupo: str(grupo["id"]))
    return matriz, _lacunas(matriz)


def _lacunas(grupos: list[dict[str, object]]) -> list[dict[str, object]]:
    lacunas: list[dict[str, object]] = []
    for grupo in grupos:
        fases = grupo["fases"]
        assert isinstance(fases, dict)
        tem_base = bool(fases["contrato"] or fases["empenho"])
        if tem_base:
            for fase in ("liquidacao", "pagamento"):
                if not fases[fase]:
                    lacunas.append(
                        {
                            "grupo": grupo["id"],
                            "fase": fase,
                            "valor": None,
                            "motivo": f"nenhum documento de {fase}",
                        }
                    )
        if grupo["apostila"] and not fases["contrato"]:
            lacunas.append(
                {
                    "grupo": grupo["id"],
                    "fase": "contrato",
                    "valor": None,
                    "motivo": "apostila sem contrato no corpus",
                }
            )
        for polo in grupo["polos_em_aberto"]:  # type: ignore[union-attr]
            lacunas.append(
                {
                    "grupo": grupo["id"],
                    "fase": "atesto",
                    "polo": polo,
                    "valor": None,
                    "motivo": "atesto de um polo nao fecha os demais",
                }
            )
        hipoteses = grupo["hipoteses"]
        assert isinstance(hipoteses, list)
        if hipoteses and not any(item["confirmada"] for item in hipoteses):
            if not any(fases[fase] for fase in FASES):
                lacunas.append(
                    {
                        "grupo": grupo["id"],
                        "fase": "planilha",
                        "valor": None,
                        "motivo": "planilha segue como hipotese ate um PDF confirmar",
                    }
                )
    return lacunas
