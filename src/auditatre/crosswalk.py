"""Cruza chaves públicas sem somar fases e sem ligar nome a sanção.

Organização, ato e vínculo são registros distintos. CNPJ comum não atribui
pagamento a contrato. Sanção não nasce de citação.
"""

from __future__ import annotations

from collections import defaultdict

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
RANK = {"confirmado": 3, "conflito": 2, "candidato": 1}


def _span(achado: Achado) -> dict[str, object]:
    return {"inicio": achado.span.inicio, "fim": achado.span.fim, "trecho": achado.span.trecho}


def _valores(doc: Documento, tipo: str) -> list[str]:
    return [achado.valor for achado in doc.achados if achado.tipo == tipo and achado.valor]


def _anexar_lista(destino: list[str], valores: list[str]) -> None:
    for valor in valores:
        if valor not in destino:
            destino.append(valor)


def _novo_ato(
    aid: str,
    tipo: str,
    unidade: str | None,
    exercicio: str | None,
    identificador: str,
    constituido: bool,
) -> dict[str, object]:
    return {
        "id": aid,
        "tipo_ato": tipo,
        "orgao_unidade": unidade,
        "exercicio": exercicio,
        "identificador": identificador,
        "constituido": constituido,
        "apostila": False,
        "fases": {fase: [] for fase in FASES},
        "itens": [],
        "hipoteses": [],
        "pessoas": [],
        "sancoes": [],
        "decisoes": [],
        "processos": [],
        "referencias": [],
        "polos_em_aberto": [],
        "documentos": [],
        "nes": [],
        "sei": [],
        "unidades": [],
        "exercicios": [],
    }


def _chave(tipo: str, unidade: str | None, exercicio: str | None, identificador: str) -> str:
    return f"ato:{tipo}|ug:{unidade or 'ausente'}|exercicio:{exercicio or 'ausente'}|id:{identificador}"


def _ano_identificador(tipo: str, valor: str) -> str | None:
    if tipo == "contrato" and "/" in valor:
        ano = valor.rsplit("/", 1)[-1]
        return ano if ano.isdigit() else None
    if tipo == "ne" and len(valor) >= 4 and valor[:4].isdigit():
        return valor[:4]
    return None


def _unidade_unica(doc: Documento) -> str | None:
    unidades = list(dict.fromkeys(_valores(doc, "unidade")))
    if len(unidades) == 1:
        return unidades[0]
    return None


def _exercicio_unico(doc: Documento) -> str | None:
    anos = list(dict.fromkeys(_valores(doc, "exercicio")))
    if len(anos) == 1:
        return anos[0]
    return None


def _garantir_org(organizacoes: dict[str, dict[str, object]], cnpj: str) -> dict[str, object]:
    oid = f"org:{cnpj}"
    return organizacoes.setdefault(
        oid,
        {"id": oid, "cnpj": cnpj, "razoes_sociais": [], "documentos": [], "evidencias": []},
    )


def _garantir_ato(
    atos: dict[str, dict[str, object]],
    tipo: str,
    unidade: str | None,
    exercicio: str | None,
    identificador: str,
    constituido: bool,
    caminho: str,
) -> dict[str, object]:
    aid = _chave(tipo, unidade, exercicio, identificador)
    existente = atos.get(aid)
    if existente is not None:
        if constituido:
            existente["constituido"] = True
        documentos = existente["documentos"]
        assert isinstance(documentos, list)
        if caminho not in documentos:
            documentos.append(caminho)
        return existente
    ato = _novo_ato(aid, tipo, unidade, exercicio, identificador, constituido)
    documentos = ato["documentos"]
    assert isinstance(documentos, list)
    documentos.append(caminho)
    atos[aid] = ato
    return ato


def _atos_do_documento(doc: Documento, atos: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    unidade = _unidade_unica(doc)
    exercicio = _exercicio_unico(doc)
    criados: list[dict[str, object]] = []
    if doc.tipo == "contrato":
        for valor in dict.fromkeys(_valores(doc, "contrato")):
            criados.append(
                _garantir_ato(atos, "contrato", unidade, _ano_identificador("contrato", valor), valor, True, doc.caminho)
            )
    elif doc.tipo == "empenho":
        for valor in dict.fromkeys(_valores(doc, "ne")):
            criados.append(
                _garantir_ato(atos, "empenho", unidade, _ano_identificador("ne", valor), valor, True, doc.caminho)
            )
    elif doc.tipo == "apostila":
        for valor in dict.fromkeys(_valores(doc, "apostila_de")):
            criados.append(
                _garantir_ato(atos, "apostila", unidade, _ano_identificador("contrato", valor), valor, True, doc.caminho)
            )
    if criados:
        return criados
    return [
        _garantir_ato(
            atos,
            doc.tipo or "outro",
            unidade,
            exercicio,
            doc.caminho,
            doc.tipo not in {"planilha", "outro"},
            doc.caminho,
        )
    ]


def _registrar_mencao(
    mencoes: list[dict[str, object]],
    ato: dict[str, object],
    tipo: str,
    achado: Achado,
    doc: Documento,
    constituido: bool,
) -> None:
    registro = {
        "tipo": tipo,
        "valor": achado.valor,
        "ato_id": ato["id"],
        "documento": doc.caminho,
        "span": _span(achado),
        "constituido": constituido,
    }
    mencoes.append(registro)
    referencias = ato["referencias"]
    assert isinstance(referencias, list)
    referencias.append(
        {
            "tipo": tipo,
            "valor": achado.valor,
            "documento": doc.caminho,
            "span": _span(achado),
            "constituido": constituido,
        }
    )


def _mencoes_do_documento(doc: Documento, atos_doc: list[dict[str, object]], mencoes: list[dict[str, object]]) -> None:
    if doc.tipo == "planilha" or doc.hipotese:
        return
    por_contrato = {str(ato["identificador"]): ato for ato in atos_doc if ato["tipo_ato"] == "contrato"}
    por_ne = {str(ato["identificador"]): ato for ato in atos_doc if ato["tipo_ato"] == "empenho"}
    por_apostila = {str(ato["identificador"]): ato for ato in atos_doc if ato["tipo_ato"] == "apostila"}
    unico = atos_doc[0] if len(atos_doc) == 1 else None
    for achado in doc.achados:
        if achado.tipo in {"contrato", "apostila_de"} and achado.valor:
            if doc.tipo == "contrato" and achado.valor in por_contrato:
                _registrar_mencao(mencoes, por_contrato[achado.valor], "contrato", achado, doc, True)
            elif doc.tipo == "apostila" and achado.valor in por_apostila:
                _registrar_mencao(mencoes, por_apostila[achado.valor], "contrato", achado, doc, False)
            elif unico is not None:
                _registrar_mencao(mencoes, unico, "contrato", achado, doc, False)
            continue
        if achado.tipo == "ne" and achado.valor:
            if doc.tipo == "empenho" and achado.valor in por_ne:
                _registrar_mencao(mencoes, por_ne[achado.valor], "ne", achado, doc, True)
            elif unico is not None:
                _registrar_mencao(mencoes, unico, "ne", achado, doc, False)
            continue
        if achado.tipo == "sei" and achado.valor and unico is not None:
            _registrar_mencao(mencoes, unico, "sei", achado, doc, False)


def _anexar_fase(ato: dict[str, object], doc: Documento) -> None:
    if doc.hipotese or doc.tipo == "planilha":
        return
    fases = ato["fases"]
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


def _anexar_juridico(ato: dict[str, object], doc: Documento) -> None:
    sancoes = ato["sancoes"]
    decisoes = ato["decisoes"]
    processos = ato["processos"]
    assert isinstance(sancoes, list) and isinstance(decisoes, list) and isinstance(processos, list)
    for achado in doc.achados:
        if achado.tipo == "sancao" and achado.detalhe and achado.valor:
            registro = {
                "penalidade": achado.detalhe.get("penalidade"),
                "destinatario": achado.detalhe.get("destinatario"),
                "ato": achado.detalhe.get("ato"),
                "datas": achado.detalhe.get("datas") or [],
                "alcances": achado.detalhe.get("alcances") or [],
                "documento": doc.caminho,
                "span": _span(achado),
            }
            if registro not in sancoes:
                sancoes.append(registro)
        elif achado.tipo == "decisao" and achado.valor:
            registro = {
                "tipo": achado.detalhe.get("tipo") if achado.detalhe else doc.tipo,
                "identificador": achado.valor,
                "documento": doc.caminho,
                "span": _span(achado),
            }
            if registro not in decisoes:
                decisoes.append(registro)
        elif achado.tipo in {"processo", "sei"} and achado.valor:
            registro = {
                "especie": achado.tipo,
                "identificador": achado.valor,
                "documento": doc.caminho,
                "span": _span(achado),
            }
            if registro not in processos:
                processos.append(registro)


def _preencher(ato: dict[str, object], doc: Documento, *, fases: bool) -> None:
    documentos = ato["documentos"]
    assert isinstance(documentos, list)
    if doc.caminho not in documentos:
        documentos.append(doc.caminho)
    _anexar_lista(ato["nes"], _valores(doc, "ne"))  # type: ignore[arg-type]
    _anexar_lista(ato["sei"], _valores(doc, "sei"))  # type: ignore[arg-type]
    _anexar_lista(ato["unidades"], _valores(doc, "unidade"))  # type: ignore[arg-type]
    _anexar_lista(ato["exercicios"], _valores(doc, "exercicio"))  # type: ignore[arg-type]
    for achado in doc.achados:
        if achado.tipo == "ne" and achado.valor and achado.valor[:4].isdigit():
            _anexar_lista(ato["exercicios"], [achado.valor[:4]])  # type: ignore[arg-type]
        if achado.tipo in {"contrato", "apostila_de"} and achado.valor and "/" in achado.valor:
            _anexar_lista(ato["exercicios"], [achado.valor.split("/")[-1]])  # type: ignore[arg-type]
        if achado.tipo == "pessoa" and achado.valor and achado.papel:
            pessoas = ato["pessoas"]
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
            itens = ato["itens"]
            assert isinstance(itens, list)
            itens.append({"valor": achado.valor, "documento": doc.caminho, "span": _span(achado)})
        if achado.tipo == "polo_em_aberto" and achado.valor:
            _anexar_lista(ato["polos_em_aberto"], [achado.valor])  # type: ignore[arg-type]
    if fases:
        _anexar_fase(ato, doc)
    _anexar_juridico(ato, doc)


def _mesma_linha(texto: str, esquerda: int, direita: int) -> bool:
    inicio = texto.rfind("\n", 0, esquerda) + 1
    fim = texto.find("\n", esquerda)
    if fim < 0:
        fim = len(texto)
    return inicio <= direita < fim


def _pares_na_linha(doc: Documento) -> list[tuple[Achado, Achado]]:
    pares: list[tuple[Achado, Achado]] = []
    offset = 0
    for linha in doc.texto.splitlines(keepends=True):
        fim = offset + len(linha)
        cnpjs = [
            achado
            for achado in doc.achados
            if achado.tipo == "cnpj_fornecedor" and achado.valor and offset <= achado.span.inicio < fim
        ]
        contratos = [
            achado
            for achado in doc.achados
            if achado.tipo in {"contrato", "apostila_de"} and achado.valor and offset <= achado.span.inicio < fim
        ]
        if len(cnpjs) == 1 and len(contratos) == 1:
            pares.append((cnpjs[0], contratos[0]))
        offset = fim
    return pares


def _anexar_razoes(org: dict[str, object], doc: Documento) -> None:
    razoes = [achado for achado in doc.achados if achado.tipo == "razao_social" and achado.valor]
    cnpjs = [achado for achado in doc.achados if achado.tipo == "cnpj_fornecedor" and achado.valor == org["cnpj"]]
    escolhidas: list[Achado] = []
    if len(cnpjs) == 1 and len(razoes) == 1:
        escolhidas = razoes
    else:
        for cnpj in cnpjs:
            for razao in razoes:
                if _mesma_linha(doc.texto, cnpj.span.inicio, razao.span.inicio):
                    escolhidas.append(razao)
    nomes = org["razoes_sociais"]
    assert isinstance(nomes, list)
    for razao in escolhidas:
        if razao.valor and razao.valor not in nomes:
            nomes.append(razao.valor)


def _contexto(doc_a: Documento, doc_b: Documento, ano: str | None) -> tuple[str, str]:
    def uma(valores: list[str]) -> tuple[str | None, str]:
        unicos = list(dict.fromkeys(valores))
        if len(unicos) > 1:
            return None, "varias"
        if len(unicos) == 1:
            return unicos[0], "uma"
        return None, "ausente"

    unidade_a, marca_a = uma(_valores(doc_a, "unidade"))
    unidade_b, marca_b = uma(_valores(doc_b, "unidade"))
    if marca_a == "varias" or marca_b == "varias":
        return "conflito", "varias unidades no documento"
    if unidade_a and unidade_b and unidade_a != unidade_b:
        return "conflito", "contexto de unidade divergente"
    if bool(unidade_a) != bool(unidade_b):
        return "candidato", "unidade ausente em um dos lados"
    if ano and any(item != ano for item in _valores(doc_a, "exercicio") + _valores(doc_b, "exercicio")):
        return "conflito", "exercicio divergente"
    return "confirmado", "identificador compartilhado"


def _canon(
    origem: dict[str, str], destino: dict[str, str]
) -> tuple[dict[str, str], dict[str, str], bool]:
    if (origem["tipo"], origem["id"]) <= (destino["tipo"], destino["id"]):
        return origem, destino, False
    return destino, origem, True


def _guardar(balde: dict[tuple[str, str, str, str], dict[str, object]], registro: dict[str, object]) -> None:
    origem = registro["origem"]
    destino = registro["destino"]
    assert isinstance(origem, dict) and isinstance(destino, dict)
    origem_c, destino_c, invertido = _canon(origem, destino)
    evidencias: list[dict[str, object]] = []
    brutas = registro["evidencias"]
    assert isinstance(brutas, list)
    for evidencia in brutas:
        assert isinstance(evidencia, dict)
        lado = str(evidencia["lado"])
        if invertido:
            lado = "destino" if lado == "origem" else "origem"
        evidencias.append({**evidencia, "lado": lado})
    estado = str(registro["estado"])
    motivo = str(registro["motivo"])
    if estado == "confirmado":
        lados = {str(item["lado"]) for item in evidencias}
        documentos = {str(item["documento"]) for item in evidencias}
        if not {"origem", "destino"} <= lados:
            estado = "candidato"
            motivo = "evidencia incompleta"
        elif origem_c["tipo"] == "ato" and destino_c["tipo"] == "ato" and len(documentos) < 2:
            estado = "candidato"
            motivo = "evidencia de um so documento"
    chave = (origem_c["tipo"], origem_c["id"], destino_c["tipo"], destino_c["id"])
    atual = balde.get(chave)
    if atual is not None and RANK[str(atual["estado"])] > RANK[estado]:
        return
    if atual is not None and atual["estado"] == estado and atual["motivo"] == motivo:
        return
    balde[chave] = {
        "origem": origem_c,
        "destino": destino_c,
        "estado": estado,
        "motivo": motivo,
        "evidencias": evidencias,
    }


def _parear_organizacao(
    doc: Documento,
    atos_doc: list[dict[str, object]],
    organizacoes: dict[str, dict[str, object]],
    balde: dict[tuple[str, str, str, str], dict[str, object]],
) -> None:
    contratos = [ato for ato in atos_doc if ato["tipo_ato"] == "contrato"]
    cnpjs = [achado for achado in doc.achados if achado.tipo == "cnpj_fornecedor" and achado.valor]
    contratos_achado = [achado for achado in doc.achados if achado.tipo in {"contrato", "apostila_de"} and achado.valor]
    locais = _pares_na_linha(doc)
    if locais and contratos:
        for cnpj, contrato in locais:
            ato = next((item for item in contratos if item["identificador"] == contrato.valor), None)
            org = organizacoes.get(f"org:{cnpj.valor}")
            if ato is None or org is None or not cnpj.valor:
                continue
            _guardar(
                balde,
                {
                    "origem": {"tipo": "ato", "id": str(ato["id"])},
                    "destino": {"tipo": "organizacao", "id": str(org["id"])},
                    "estado": "confirmado",
                    "motivo": "pareamento de cnpj e contrato",
                    "evidencias": [
                        {"lado": "origem", "documento": doc.caminho, "span": _span(contrato)},
                        {"lado": "destino", "documento": doc.caminho, "span": _span(cnpj)},
                    ],
                },
            )
        return
    if len(cnpjs) == 1 and len(contratos) == 1 and cnpjs[0].valor:
        org = organizacoes.get(f"org:{cnpjs[0].valor}")
        if org is None:
            return
        _guardar(
            balde,
            {
                "origem": {"tipo": "ato", "id": str(contratos[0]["id"])},
                "destino": {"tipo": "organizacao", "id": str(org["id"])},
                "estado": "confirmado",
                "motivo": "pareamento de cnpj e contrato",
                "evidencias": [
                    {"lado": "origem", "documento": doc.caminho, "span": _span(contratos_achado[0])},
                    {"lado": "destino", "documento": doc.caminho, "span": _span(cnpjs[0])},
                ],
            },
        )
        return
    if (len(cnpjs) > 1 and len(contratos_achado) > 1) or (len(cnpjs) > 1 and len(contratos) == 1) or (
        len(cnpjs) >= 1 and len(contratos) > 1
    ):
        _guardar(
            balde,
            {
                "origem": {"tipo": "documento", "id": doc.caminho},
                "destino": {"tipo": "documento", "id": doc.caminho},
                "estado": "conflito",
                "motivo": "varios cnpjs e contratos sem pareamento",
                "evidencias": [
                    {"lado": "origem" if achado.tipo == "cnpj_fornecedor" else "destino", "documento": doc.caminho, "span": _span(achado)}
                    for achado in cnpjs + contratos_achado
                ],
            },
        )
        return
    for cnpj in cnpjs:
        org = organizacoes.get(f"org:{cnpj.valor}")
        if org is None:
            continue
        for ato in atos_doc:
            _guardar(
                balde,
                {
                    "origem": {"tipo": "ato", "id": str(ato["id"])},
                    "destino": {"tipo": "organizacao", "id": str(org["id"])},
                    "estado": "candidato",
                    "motivo": "cnpj comum sem referencia ao ato",
                    "evidencias": [{"lado": "destino", "documento": doc.caminho, "span": _span(cnpj)}],
                },
            )


def _ligar_identificadores(
    mencoes: list[dict[str, object]],
    docs: dict[str, Documento],
    balde: dict[tuple[str, str, str, str], dict[str, object]],
) -> None:
    grupos: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for mencao in mencoes:
        grupos[(str(mencao["tipo"]), str(mencao["valor"]))].append(mencao)
    for (tipo, valor), itens in grupos.items():
        constituidos: list[dict[str, object]] = []
        vistos: list[str] = []
        for item in itens:
            if not item["constituido"]:
                continue
            ato_id = str(item["ato_id"])
            if ato_id not in vistos:
                vistos.append(ato_id)
                constituidos.append(item)
        distintos: list[str] = []
        for item in itens:
            ato_id = str(item["ato_id"])
            if ato_id not in distintos:
                distintos.append(ato_id)
        if len(vistos) > 1:
            for indice, esquerda in enumerate(vistos):
                for direita in vistos[indice + 1 :]:
                    men_esq = next(item for item in constituidos if item["ato_id"] == esquerda)
                    men_dir = next(item for item in constituidos if item["ato_id"] == direita)
                    _guardar(
                        balde,
                        {
                            "origem": {"tipo": "ato", "id": esquerda},
                            "destino": {"tipo": "ato", "id": direita},
                            "estado": "conflito",
                            "motivo": "varios alvos para o mesmo identificador",
                            "evidencias": [
                                {"lado": "origem", "documento": men_esq["documento"], "span": men_esq["span"]},
                                {"lado": "destino", "documento": men_dir["documento"], "span": men_dir["span"]},
                            ],
                        },
                    )
            continue
        if len(vistos) == 1:
            destino = constituidos[0]
            for item in itens:
                if str(item["ato_id"]) == str(destino["ato_id"]):
                    continue
                doc_item = docs.get(str(item["documento"]))
                doc_destino = docs.get(str(destino["documento"]))
                if doc_item is None or doc_destino is None:
                    estado, motivo = "candidato", "evidencia incompleta"
                else:
                    estado, motivo = _contexto(doc_item, doc_destino, _ano_identificador(tipo, valor))
                _guardar(
                    balde,
                    {
                        "origem": {"tipo": "ato", "id": str(item["ato_id"])},
                        "destino": {"tipo": "ato", "id": str(destino["ato_id"])},
                        "estado": estado,
                        "motivo": motivo,
                        "evidencias": [
                            {"lado": "origem", "documento": item["documento"], "span": item["span"]},
                            {"lado": "destino", "documento": destino["documento"], "span": destino["span"]},
                        ],
                    },
                )
            continue
        if tipo == "sei" and len(distintos) >= 2:
            base = next(item for item in itens if str(item["ato_id"]) == distintos[0])
            compativel = True
            for ato_id in distintos[1:]:
                outro = next(item for item in itens if str(item["ato_id"]) == ato_id)
                doc_base = docs.get(str(base["documento"]))
                doc_outro = docs.get(str(outro["documento"]))
                if doc_base is None or doc_outro is None:
                    estado, motivo = "candidato", "evidencia incompleta"
                else:
                    estado, motivo = _contexto(doc_base, doc_outro, None)
                if estado != "confirmado":
                    compativel = False
                    _guardar(
                        balde,
                        {
                            "origem": {"tipo": "ato", "id": str(base["ato_id"])},
                            "destino": {"tipo": "ato", "id": ato_id},
                            "estado": estado,
                            "motivo": motivo,
                            "evidencias": [
                                {"lado": "origem", "documento": base["documento"], "span": base["span"]},
                                {"lado": "destino", "documento": outro["documento"], "span": outro["span"]},
                            ],
                        },
                    )
            if compativel:
                for ato_id in distintos[1:]:
                    outro = next(item for item in itens if str(item["ato_id"]) == ato_id)
                    _guardar(
                        balde,
                        {
                            "origem": {"tipo": "ato", "id": str(base["ato_id"])},
                            "destino": {"tipo": "ato", "id": ato_id},
                            "estado": "confirmado",
                            "motivo": "processo sei compartilhado",
                            "evidencias": [
                                {"lado": "origem", "documento": base["documento"], "span": base["span"]},
                                {"lado": "destino", "documento": outro["documento"], "span": outro["span"]},
                            ],
                        },
                    )
            continue
        if len(distintos) >= 2:
            base_id = distintos[0]
            base = next(item for item in itens if str(item["ato_id"]) == base_id)
            for ato_id in distintos[1:]:
                outro = next(item for item in itens if str(item["ato_id"]) == ato_id)
                _guardar(
                    balde,
                    {
                        "origem": {"tipo": "ato", "id": base_id},
                        "destino": {"tipo": "ato", "id": ato_id},
                        "estado": "candidato",
                        "motivo": "referencia sem ato constituido",
                        "evidencias": [
                            {"lado": "origem", "documento": base["documento"], "span": base["span"]},
                            {"lado": "destino", "documento": outro["documento"], "span": outro["span"]},
                        ],
                    },
                )


def _ligar_sancoes(
    atos: dict[str, dict[str, object]],
    organizacoes: dict[str, dict[str, object]],
    balde: dict[tuple[str, str, str, str], dict[str, object]],
) -> None:
    for ato in atos.values():
        sancoes = ato["sancoes"]
        assert isinstance(sancoes, list)
        for sancao in sancoes:
            destinatario = sancao.get("destinatario")
            if not isinstance(destinatario, dict) or not destinatario.get("cnpj"):
                continue
            org = organizacoes.get(f"org:{destinatario['cnpj']}")
            if org is None or not isinstance(sancao.get("span"), dict) or not isinstance(destinatario.get("span"), dict):
                continue
            _guardar(
                balde,
                {
                    "origem": {"tipo": "ato", "id": str(ato["id"])},
                    "destino": {"tipo": "organizacao", "id": str(org["id"])},
                    "estado": "confirmado",
                    "motivo": "destinatario da penalidade documentada",
                    "evidencias": [
                        {"lado": "origem", "documento": sancao["documento"], "span": sancao["span"]},
                        {"lado": "destino", "documento": sancao["documento"], "span": destinatario["span"]},
                    ],
                },
            )


def _marcar_apostilas(atos: dict[str, dict[str, object]], vinculos: list[dict[str, object]]) -> None:
    for vinculo in vinculos:
        if vinculo["estado"] != "confirmado":
            continue
        origem = vinculo["origem"]
        destino = vinculo["destino"]
        assert isinstance(origem, dict) and isinstance(destino, dict)
        if origem["tipo"] != "ato" or destino["tipo"] != "ato":
            continue
        esquerda = atos.get(str(origem["id"]))
        direita = atos.get(str(destino["id"]))
        if esquerda is None or direita is None:
            continue
        par = {esquerda["tipo_ato"], direita["tipo_ato"]}
        if "apostila" not in par or "contrato" not in par:
            continue
        contrato = esquerda if esquerda["tipo_ato"] == "contrato" else direita
        if contrato["constituido"]:
            contrato["apostila"] = True


def _indice_constituido(mencoes: list[dict[str, object]]) -> dict[tuple[str, str], list[str]]:
    indice: dict[tuple[str, str], list[str]] = defaultdict(list)
    for mencao in mencoes:
        if not mencao["constituido"]:
            continue
        chave = (str(mencao["tipo"]), str(mencao["valor"]))
        ato_id = str(mencao["ato_id"])
        if ato_id not in indice[chave]:
            indice[chave].append(ato_id)
    return indice


def _anexar_hipotese(
    doc: Documento,
    atos: dict[str, dict[str, object]],
    por_doc: dict[str, list[dict[str, object]]],
    indice: dict[tuple[str, str], list[str]],
    balde: dict[tuple[str, str, str, str], dict[str, object]],
) -> None:
    alvos: list[str] = []
    for achado in doc.achados:
        if achado.tipo == "ne" and achado.valor:
            alvos.extend(indice.get(("ne", achado.valor), []))
        if achado.tipo in {"contrato", "apostila_de"} and achado.valor:
            alvos.extend(indice.get(("contrato", achado.valor), []))
    unicos: list[str] = []
    for ato_id in alvos:
        if ato_id not in unicos:
            unicos.append(ato_id)
    do_documento = por_doc.get(doc.caminho, [])
    proprio = do_documento[0] if do_documento else None
    if len(unicos) > 1 and proprio is not None:
        _guardar(
            balde,
            {
                "origem": {"tipo": "ato", "id": str(proprio["id"])},
                "destino": {"tipo": "ato", "id": unicos[0]},
                "estado": "conflito",
                "motivo": "planilha com varios alvos",
                "evidencias": [],
            },
        )
    destino = atos[unicos[0]] if len(unicos) == 1 else proprio
    if destino is None:
        return
    documentos = destino["documentos"]
    assert isinstance(documentos, list)
    if doc.caminho not in documentos:
        documentos.append(doc.caminho)
    hipoteses = destino["hipoteses"]
    assert isinstance(hipoteses, list)
    fases = destino["fases"]
    assert isinstance(fases, dict)
    for achado in doc.achados:
        fase = HIPOTESE_DA_FASE.get(achado.tipo)
        if not fase or not achado.valor:
            continue
        confirmada = False
        if len(unicos) == 1:
            confirmada = any(item["valor"] == achado.valor for item in fases.get(fase, []))
        hipoteses.append(
            {
                "fase": fase,
                "valor": achado.valor,
                "documento": doc.caminho,
                "confirmada": confirmada,
                "span": _span(achado),
            }
        )


def _componentes(
    atos: dict[str, dict[str, object]], vinculos: list[dict[str, object]]
) -> dict[str, list[dict[str, object]]]:
    parent = {ato_id: ato_id for ato_id in atos}
    def find(atual: str) -> str:
        while parent[atual] != atual:
            parent[atual] = parent[parent[atual]]
            atual = parent[atual]
        return atual

    for vinculo in vinculos:
        if vinculo["estado"] != "confirmado":
            continue
        origem = vinculo["origem"]
        destino = vinculo["destino"]
        assert isinstance(origem, dict) and isinstance(destino, dict)
        if origem["tipo"] != "ato" or destino["tipo"] != "ato":
            continue
        esquerda, direita = str(origem["id"]), str(destino["id"])
        if esquerda not in parent or direita not in parent:
            continue
        raiz_esquerda, raiz_direita = find(esquerda), find(direita)
        if raiz_esquerda != raiz_direita:
            parent[raiz_direita] = raiz_esquerda
    grupos: dict[str, list[dict[str, object]]] = defaultdict(list)
    for ato_id, ato in atos.items():
        grupos[find(ato_id)].append(ato)
    return grupos


def _lacunas(atos: dict[str, dict[str, object]], vinculos: list[dict[str, object]]) -> list[dict[str, object]]:
    lacunas: list[dict[str, object]] = []
    for membros in _componentes(atos, vinculos).values():
        fases: dict[str, list[dict[str, object]]] = {fase: [] for fase in FASES}
        for ato in membros:
            do_ato = ato["fases"]
            assert isinstance(do_ato, dict)
            for fase in FASES:
                fases[fase].extend(do_ato[fase])
        constituidos = [ato for ato in membros if ato["tipo_ato"] == "contrato" and ato["constituido"]]
        if not constituidos:
            constituidos = [ato for ato in membros if ato["tipo_ato"] == "empenho" and ato["constituido"]]
        if not constituidos:
            continue
        ancora = sorted(constituidos, key=lambda item: str(item["id"]))[0]
        if fases["contrato"] or fases["empenho"]:
            for fase in ("liquidacao", "pagamento"):
                if not fases[fase]:
                    lacunas.append(
                        {
                            "grupo": ancora["id"],
                            "fase": fase,
                            "valor": None,
                            "motivo": f"nenhum documento de {fase}",
                        }
                    )
    for ato in atos.values():
        if ato["tipo_ato"] != "apostila":
            continue
        ligado = False
        for vinculo in vinculos:
            if vinculo["estado"] != "confirmado":
                continue
            origem = vinculo["origem"]
            destino = vinculo["destino"]
            assert isinstance(origem, dict) and isinstance(destino, dict)
            ids = {str(origem["id"]), str(destino["id"])}
            if str(ato["id"]) not in ids:
                continue
            outro_id = (ids - {str(ato["id"])}).pop()
            outro = atos.get(outro_id)
            if outro and outro["tipo_ato"] == "contrato" and outro["constituido"]:
                ligado = True
        if not ligado:
            lacunas.append(
                {
                    "grupo": ato["id"],
                    "fase": "contrato",
                    "valor": None,
                    "motivo": "apostila sem contrato no corpus",
                }
            )
        hipoteses = ato["hipoteses"]
        assert isinstance(hipoteses, list)
        fases_ato = ato["fases"]
        assert isinstance(fases_ato, dict)
        if hipoteses and not any(item["confirmada"] for item in hipoteses) and not any(fases_ato[fase] for fase in FASES):
            lacunas.append(
                {
                    "grupo": ato["id"],
                    "fase": "planilha",
                    "valor": None,
                    "motivo": "planilha segue como hipotese ate um PDF confirmar",
                }
            )
        for polo in ato["polos_em_aberto"]:  # type: ignore[union-attr]
            lacunas.append(
                {
                    "grupo": ato["id"],
                    "fase": "atesto",
                    "polo": polo,
                    "valor": None,
                    "motivo": "atesto de um polo nao fecha os demais",
                }
            )
    for ato in atos.values():
        if ato["tipo_ato"] == "apostila":
            continue
        hipoteses = ato["hipoteses"]
        assert isinstance(hipoteses, list)
        fases_ato = ato["fases"]
        assert isinstance(fases_ato, dict)
        if hipoteses and not any(item["confirmada"] for item in hipoteses) and not any(fases_ato[fase] for fase in FASES):
            lacunas.append(
                {
                    "grupo": ato["id"],
                    "fase": "planilha",
                    "valor": None,
                    "motivo": "planilha segue como hipotese ate um PDF confirmar",
                }
            )
        for polo in ato["polos_em_aberto"]:  # type: ignore[union-attr]
            lacunas.append(
                {
                    "grupo": ato["id"],
                    "fase": "atesto",
                    "polo": polo,
                    "valor": None,
                    "motivo": "atesto de um polo nao fecha os demais",
                }
            )
    return lacunas


def cruzar(documentos: list[Documento]) -> tuple[dict[str, list[dict[str, object]]], list[dict[str, object]]]:
    organizacoes: dict[str, dict[str, object]] = {}
    atos: dict[str, dict[str, object]] = {}
    mencoes: list[dict[str, object]] = []
    balde: dict[tuple[str, str, str, str], dict[str, object]] = {}
    docs = {doc.caminho: doc for doc in documentos}
    por_doc: dict[str, list[dict[str, object]]] = defaultdict(list)

    for doc in documentos:
        for achado in doc.achados:
            if achado.tipo == "cnpj_fornecedor" and achado.valor:
                org = _garantir_org(organizacoes, achado.valor)
                evidencias = org["evidencias"]
                documentos_org = org["documentos"]
                assert isinstance(evidencias, list) and isinstance(documentos_org, list)
                evidencia = {"documento": doc.caminho, "span": _span(achado)}
                if evidencia not in evidencias:
                    evidencias.append(evidencia)
                if doc.caminho not in documentos_org:
                    documentos_org.append(doc.caminho)
                _anexar_razoes(org, doc)

    ordenados = sorted(documentos, key=lambda item: (ORDEM.get(item.tipo, 50), item.caminho))
    for doc in ordenados:
        atos_doc = _atos_do_documento(doc, atos)
        por_doc[doc.caminho] = atos_doc
        if len(atos_doc) == 1:
            _preencher(atos_doc[0], doc, fases=not doc.hipotese and doc.tipo != "planilha")
        else:
            for ato in atos_doc:
                documentos_ato = ato["documentos"]
                assert isinstance(documentos_ato, list)
                if doc.caminho not in documentos_ato:
                    documentos_ato.append(doc.caminho)
        _mencoes_do_documento(doc, atos_doc, mencoes)
        _parear_organizacao(doc, atos_doc, organizacoes, balde)

    _ligar_identificadores(mencoes, docs, balde)
    _ligar_sancoes(atos, organizacoes, balde)
    indice = _indice_constituido(mencoes)
    for doc in ordenados:
        if doc.tipo == "planilha" or doc.hipotese:
            _anexar_hipotese(doc, atos, por_doc, indice, balde)

    vinculos = sorted(
        balde.values(),
        key=lambda item: (str(item["estado"]), str(item["motivo"]), str(item["origem"]["id"]), str(item["destino"]["id"])),  # type: ignore[index]
    )
    for numero, vinculo in enumerate(vinculos, start=1):
        vinculo["id"] = f"v{numero:04d}"
    _marcar_apostilas(atos, vinculos)
    matriz = {
        "organizacoes": sorted(organizacoes.values(), key=lambda item: str(item["id"])),
        "atos": sorted(atos.values(), key=lambda item: str(item["id"])),
        "vinculos": vinculos,
    }
    return matriz, _lacunas(atos, vinculos)
