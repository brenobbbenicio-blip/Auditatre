"""Extrai chaves públicas e papéis nomeados. Não lê endereço, telefone nem CPF mascarado."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser

CNPJ_RE = re.compile(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}")
CPF_PONTUADO = re.compile(r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)")
CPF_MASCARADO = re.compile(r"\*{2,}[\d.*\-]{0,20}")
SEI_CHEIO = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")
NE_COLADO = re.compile(r"(?<!\d)(\d{4})\s*NE\s*0*(\d{1,6})(?!\d)", re.IGNORECASE)
NE_CAMPOS = re.compile(
    r"Ano\s+Tipo\s+N[úu]mero\s+(\d{4})\s+NE\s+(\d{1,6})",
    re.IGNORECASE,
)
CONTRATO_RE = re.compile(
    r"contrat(?:o|os)\s*n[ºo°.]?\s*0*(\d{1,5})\s*/\s*(\d{4})",
    re.IGNORECASE,
)
CONTRATO_CT = re.compile(r"\bCT\s*[-_]?\s*0*(\d{1,5})\s*[/_-]\s*(\d{4})", re.IGNORECASE)
VALOR_RE = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})")
EMPRESA_RE = re.compile(
    r"([A-ZÁÉÍÓÚÃÕÇ0-9&][A-ZÁÉÍÓÚÃÕÇ0-9& .'\-]{2,80}?"
    r"(?:LTDA|S\.A\.|S/A|EIRELI|EPP|ME))\b"
)
PAPEL_LINHA = re.compile(
    r"(ordenador(?:\s+de\s+despesas?)?|fiscal(?:\s+do\s+contrato)?|pregoeiro|"
    r"atestante|benefici[áa]rio(?:\s+de\s+di[áa]rias?)?)"
    r"\s*[:\-]\s*([A-ZÁÉÍÓÚÃÕÇ][A-Za-zÁÉÍÓÚÃÕÂÊÔÇáéíóúãõâêôç' ]{4,80})",
    re.IGNORECASE,
)
POLO_RE = re.compile(
    r"\b(?:polo\s+)?(Marab[áa]|Santar[ée]m|Bel[ée]m)\b",
    re.IGNORECASE,
)
TELEFONE_RE = re.compile(r"\(?\d{2}\)?\s*\d{4,5}-?\d{4}")
CEP_RE = re.compile(r"\b\d{5}-?\d{3}\b")

PALAVRAS_NAO_NOME = {
    "tribunal",
    "regional",
    "eleitoral",
    "nota",
    "empenho",
    "contrato",
    "contratante",
    "contratado",
    "gestor",
    "financeiro",
    "ordenador",
    "despesa",
    "despesas",
    "fiscal",
    "pregoeiro",
    "atestante",
    "beneficiario",
    "diaria",
    "diarias",
    "ltda",
    "eireli",
    "sei",
    "cnpj",
    "para",
    "real",
    "unidade",
    "gestora",
}

PAPEIS = {
    "ordenador": "ordenador",
    "fiscal": "fiscal",
    "pregoeiro": "pregoeiro",
    "atestante": "atestante",
    "beneficiario": "beneficiario_diaria",
    "beneficiário": "beneficiario_diaria",
}


@dataclass(frozen=True)
class Span:
    inicio: int
    fim: int
    trecho: str


@dataclass
class Achado:
    tipo: str
    valor: str | None
    span: Span
    hipotese: bool = False
    papel: str | None = None
    doc: str = ""
    pessoa_ref: str | None = None

    def __post_init__(self) -> None:
        if self.span is None or self.span.fim <= self.span.inicio or not self.span.trecho:
            raise ValueError("achado exige span")


@dataclass
class Documento:
    caminho: str
    tipo: str
    texto: str
    hipotese: bool
    achados: list[Achado] = field(default_factory=list)


def somente_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor)


def _dv(base: str, pesos: list[int]) -> str:
    total = sum(int(digito) * peso for digito, peso in zip(base, pesos))
    resto = total % 11
    return "0" if resto < 2 else str(11 - resto)


def cnpj_valido(valor: str) -> bool:
    digitos = somente_digitos(valor)
    if len(digitos) != 14 or digitos == digitos[0] * 14:
        return False
    primeiro = _dv(digitos[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    segundo = _dv(digitos[:12] + primeiro, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return digitos[-2:] == primeiro + segundo


def cpf_valido(valor: str) -> bool:
    digitos = somente_digitos(valor)
    if len(digitos) != 11 or digitos == digitos[0] * 11:
        return False
    primeiro = _dv(digitos[:9], list(range(10, 1, -1)))
    segundo = _dv(digitos[:9] + primeiro, list(range(11, 1, -1)))
    return digitos[-2:] == primeiro + segundo


def formatar_cnpj(valor: str) -> str:
    digitos = somente_digitos(valor)
    return f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}"


def valor_canonico(bruto: str) -> str | None:
    texto = bruto.strip().replace("R$", "").strip()
    if not texto or texto in {"0", "0,00", "0.00"}:
        return None
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    inteiro, _, decimal = texto.partition(".")
    if not inteiro.isdigit():
        return None
    decimal = (decimal + "00")[:2]
    if not decimal.isdigit():
        return None
    if int(inteiro) == 0 and int(decimal) == 0:
        return None
    return f"{int(inteiro)}.{decimal}"


def ne_canonico(ano: str, numero: str) -> str:
    return f"{ano}NE{int(numero):06d}"


def contrato_canonico(numero: str, ano: str) -> str:
    return f"{int(numero)}/{ano}"


def _span(texto: str, inicio: int, fim: int) -> Span:
    trecho = texto[inicio:fim].strip()
    if not trecho:
        raise ValueError("achado exige span")
    return Span(inicio, fim, trecho[:240])


def _sem_acento(texto: str) -> str:
    normal = unicodedata.normalize("NFD", texto)
    return "".join(caractere for caractere in normal if unicodedata.category(caractere) != "Mn")


def classificar(caminho: str, texto: str) -> str:
    nome = caminho.rsplit("/", 1)[-1].lower()
    nome = _sem_acento(nome)
    cabeca = _sem_acento(texto[:1800].lower())
    if nome.endswith((".xlsx", ".xls", ".csv", ".ods")):
        if "folha de pagamento" in cabeca and "servidor" in cabeca:
            return "folha"
        return "planilha"
    if nome.endswith(".zip"):
        return "zip"
    if "ceis" in nome or "cnep" in nome or cabeca.startswith("ceis") or cabeca.startswith("cnep"):
        return "sancao"
    if "acordao" in nome or cabeca.startswith("acordao"):
        return "acordao"
    if "sentenca" in nome or cabeca.startswith("sentenca"):
        return "sentenca"
    if "certidao" in nome or cabeca.startswith("certidao"):
        return "certidao"
    if "apostil" in nome or "termo de apostilamento" in cabeca or cabeca.startswith("apostila"):
        return "apostila"
    primeira = cabeca.strip().splitlines()[0] if cabeca.strip() else ""
    if "nota de empenho" in primeira or re.search(r"\d{4}ne\d{3,6}", nome):
        return "empenho"
    if "liquidac" in nome or cabeca.startswith("nota de liquidacao"):
        return "liquidacao"
    if "ordem bancaria" in nome or "pagamento" in nome:
        return "pagamento"
    if "prestacao de conta" in nome or "prestacao de contas" in cabeca[:400]:
        return "prestacao"
    if re.search(r"\bdiarias?\b", nome) or cabeca.startswith("diaria"):
        return "diaria"
    if "folha" in nome and "servidor" in cabeca:
        return "folha"
    if "remunerac" in nome:
        return "remuneracao"
    if nome.startswith("ata") or re.search(r"(^|/)ata[\W_]", nome) or cabeca.startswith("ata "):
        return "ata"
    if "contrato" in nome or "contrato" in cabeca[:500]:
        return "contrato"
    return "outro"


def _papel_canonico(rotulo: str) -> str:
    base = _sem_acento(rotulo).lower().split()[0]
    return PAPEIS.get(base, base)


def _nome_aceitavel(nome: str) -> bool:
    partes = [parte for parte in re.split(r"\s+", nome.strip()) if parte]
    if len(partes) < 2 or len(partes) > 8:
        return False
    for parte in partes:
        if any(caractere.isdigit() for caractere in parte):
            return False
        if _sem_acento(parte).lower() in PALAVRAS_NAO_NOME:
            return False
    return True


def _janela(texto: str, inicio: int, tamanho: int = 220) -> str:
    return _sem_acento(texto[max(0, inicio - tamanho) : inicio].lower())


def extrair(caminho: str, texto: str, *, hipotese: bool = False, sal: bytes | None = None) -> Documento:
    tipo = classificar(caminho, texto)
    doc = Documento(caminho=caminho, tipo=tipo, texto=texto, hipotese=hipotese or tipo == "planilha")
    doc._sal = sal  # type: ignore[attr-defined]
    if not texto.strip():
        return doc
    _cnpjs(doc)
    _sei(doc)
    _contratos(doc)
    _nes(doc)
    if doc.tipo == "planilha":
        _valores_planilha(doc)
    else:
        _valores(doc)
    _empresas(doc)
    _pessoas(doc)
    _polos(doc)
    _sancao(doc)
    _exercicio_unidade(doc)
    return doc


def _adicionar(doc: Documento, tipo: str, valor: str | None, inicio: int, fim: int, **kwargs: object) -> None:
    doc.achados.append(
        Achado(
            tipo=tipo,
            valor=valor,
            span=_span(doc.texto, inicio, fim),
            hipotese=bool(kwargs.get("hipotese", doc.hipotese)),
            papel=kwargs.get("papel") if isinstance(kwargs.get("papel"), str) else None,
            doc=doc.caminho,
            pessoa_ref=kwargs.get("pessoa_ref") if isinstance(kwargs.get("pessoa_ref"), str) else None,
        )
    )


def _cnpjs(doc: Documento) -> None:
    for match in CNPJ_RE.finditer(doc.texto):
        bruto = match.group(0)
        if not cnpj_valido(bruto):
            _adicionar(doc, "cnpj_ilegivel", bruto, match.start(), match.end())
            continue
        janela = _janela(doc.texto, match.start())
        if "contratado" in janela or "favorecido" in janela:
            tipo = "cnpj_fornecedor"
        elif "contratante" in janela or "ug emitente" in janela or "tribunal regional eleitoral" in janela:
            tipo = "cnpj_orgao"
        else:
            tipo = "cnpj_fornecedor"
        _adicionar(doc, tipo, formatar_cnpj(bruto), match.start(), match.end())


def _sei(doc: Documento) -> None:
    for match in SEI_CHEIO.finditer(doc.texto):
        _adicionar(doc, "sei", match.group(0), match.start(), match.end())


def _contratos(doc: Documento) -> None:
    vistos: set[str] = set()
    for regex in (CONTRATO_RE, CONTRATO_CT):
        for match in regex.finditer(doc.texto):
            canonico = contrato_canonico(match.group(1), match.group(2))
            if canonico in vistos:
                continue
            vistos.add(canonico)
            tipo = "apostila_de" if doc.tipo == "apostila" else "contrato"
            _adicionar(doc, tipo, canonico, match.start(), match.end())


def _nes(doc: Documento) -> None:
    vistos: set[str] = set()
    for match in NE_CAMPOS.finditer(doc.texto):
        canonico = ne_canonico(match.group(1), match.group(2))
        vistos.add(canonico)
        _adicionar(doc, "ne", canonico, match.start(), match.end())
    for match in NE_COLADO.finditer(doc.texto):
        canonico = ne_canonico(match.group(1), match.group(2))
        if canonico in vistos:
            continue
        vistos.add(canonico)
        _adicionar(doc, "ne", canonico, match.start(), match.end())


def _classificar_valor(doc: Documento, inicio: int, fim: int) -> str:
    janela = _sem_acento(doc.texto[max(0, inicio - 90) : fim].lower())
    if "valor do item" in janela or "valor unitario" in janela or "valor total" in janela:
        return "valor_item"
    if "valor global" in janela:
        return "valor_contrato"
    if "liquidac" in janela or doc.tipo == "liquidacao":
        return "valor_liquidacao"
    if "ordem bancaria" in janela or doc.tipo == "pagamento":
        return "valor_pagamento"
    if doc.tipo == "empenho" or "nota de empenho" in janela:
        return "valor_item" if "item" in janela else "valor_empenho"
    if doc.tipo == "contrato" and "contrato" in janela:
        return "valor_contrato"
    return "valor_mencionado"


def _valores(doc: Documento) -> None:
    vistos: set[tuple[str, str]] = set()
    padroes = [VALOR_RE]
    if doc.tipo in {"empenho", "liquidacao", "pagamento"}:
        padroes.append(re.compile(r"(?<!\d)(\d{1,3}(?:\.\d{3})+,\d{2})(?!\d)"))
    for regex in padroes:
        for match in regex.finditer(doc.texto):
            canonico = valor_canonico(match.group(1))
            if canonico is None:
                continue
            tipo = _classificar_valor(doc, match.start(), match.end())
            if tipo == "valor_mencionado":
                continue
            chave = (tipo, canonico)
            if chave in vistos:
                continue
            vistos.add(chave)
            _adicionar(doc, tipo, canonico, match.start(1), match.end(1), hipotese=False)


def _valores_planilha(doc: Documento) -> None:
    for linha in doc.texto.splitlines():
        for match in re.finditer(r"([^|=\n]+)=\s*([^|\n]+)", linha):
            rotulo = _sem_acento(match.group(1)).lower()
            bruto = match.group(2)
            valor = None
            encontrado = VALOR_RE.search(bruto) or re.search(r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})", bruto)
            if encontrado:
                valor = valor_canonico(encontrado.group(1))
            if valor is None:
                continue
            if "liquid" in rotulo:
                tipo = "hipotese_liquidacao"
            elif "pag" in rotulo or "pago" in rotulo:
                tipo = "hipotese_pagamento"
            elif "empenh" in rotulo:
                tipo = "hipotese_empenho"
            elif "contrato" in rotulo:
                tipo = "hipotese_contrato"
            else:
                tipo = "hipotese_valor"
            inicio = doc.texto.find(bruto)
            if inicio < 0:
                continue
            _adicionar(doc, tipo, valor, inicio, inicio + len(bruto), hipotese=True)


def _empresas(doc: Documento) -> None:
    for match in EMPRESA_RE.finditer(doc.texto):
        nome = re.sub(r"\s+", " ", match.group(1)).strip(" ,")
        if len(nome) < 4:
            continue
        _adicionar(doc, "razao_social", nome, match.start(1), match.end(1))
    favorecido = re.compile(
        r"Favorecido(?:\s+C[óo]digo)?(?:\s+Nome)?\s+"
        r"(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})\s+\S+\s+"
        r"([A-ZÁÉÍÓÚÃÕÇ][A-ZÁÉÍÓÚÃÕÇ ]{5,80}?)"
        r"(?=\s+(?:Endere[çc]o|CEP|Rua|Telefone|Munic[íi]pio)|$)",
        re.IGNORECASE,
    )
    for match in favorecido.finditer(doc.texto):
        nome = re.sub(r"\s+", " ", match.group(2)).strip()
        if _nome_aceitavel(nome) or len(nome.split()) >= 2:
            _adicionar(doc, "razao_social", nome, match.start(2), match.end(2))


def _ref_pessoa(doc: Documento, linha: str) -> str | None:
    sal = getattr(doc, "_sal", None)
    if not sal:
        return None
    for match in CPF_PONTUADO.finditer(linha):
        if cpf_valido(match.group(0)):
            import hashlib
            import hmac

            return hmac.new(sal, somente_digitos(match.group(0)).encode(), hashlib.sha256).hexdigest()[:16]
    return None


def _pessoas(doc: Documento) -> None:
    if doc.tipo in {"planilha", "terceirizados"}:
        return
    for match in PAPEL_LINHA.finditer(doc.texto):
        nome = re.sub(r"\s+", " ", match.group(2)).strip(" .,-")
        if not _nome_aceitavel(nome):
            continue
        linha = doc.texto[doc.texto.rfind("\n", 0, match.start()) + 1 : doc.texto.find("\n", match.end())]
        if doc.texto.find("\n", match.end()) < 0:
            linha = doc.texto[doc.texto.rfind("\n", 0, match.start()) + 1 :]
        _adicionar(
            doc,
            "pessoa",
            nome,
            match.start(2),
            match.end(2),
            papel=_papel_canonico(match.group(1)),
            hipotese=False,
            pessoa_ref=_ref_pessoa(doc, linha),
        )
    if doc.tipo == "folha":
        linhas = doc.texto.splitlines()
        for indice, linha in enumerate(linhas):
            match = re.fullmatch(r"[A-ZÁÉÍÓÚÃÕÇ][A-ZÁÉÍÓÚÃÕÇ ]{8,80}", linha.strip())
            if not match or not _nome_aceitavel(linha.strip()):
                continue
            inicio = doc.texto.find(linha.strip())
            if inicio < 0:
                continue
            janela = linha if indice + 1 >= len(linhas) else linha + "\n" + linhas[indice + 1]
            _adicionar(
                doc,
                "pessoa",
                linha.strip(),
                inicio,
                inicio + len(linha.strip()),
                papel="servidor_folha",
                hipotese=False,
                pessoa_ref=_ref_pessoa(doc, janela),
            )


def _polos(doc: Documento) -> None:
    mencionados: list[tuple[str, int, int]] = []
    for match in POLO_RE.finditer(doc.texto):
        polo = _sem_acento(match.group(1)).lower()
        mencionados.append((polo, match.start(1), match.end(1)))
        _adicionar(doc, "polo", polo, match.start(1), match.end(1), hipotese=False)
    if doc.tipo == "planilha":
        return
    atestados: set[str] = set()
    for frase in re.split(r"[\n.]", doc.texto):
        if not re.search(r"\batest", _sem_acento(frase).lower()):
            continue
        for match in POLO_RE.finditer(frase):
            atestados.add(_sem_acento(match.group(1)).lower())
    if not atestados:
        return
    vistos: set[str] = set()
    for polo, inicio, fim in mencionados:
        if polo in atestados or polo in vistos:
            continue
        vistos.add(polo)
        _adicionar(doc, "polo_em_aberto", polo, inicio, fim, hipotese=False)


def _sancao(doc: Documento) -> None:
    if doc.tipo not in {"sancao", "acordao", "sentenca"}:
        return
    for achado in list(doc.achados):
        if achado.tipo == "cnpj_fornecedor" and achado.valor:
            _adicionar(doc, "sancao", achado.valor, achado.span.inicio, achado.span.fim, hipotese=False)


def _exercicio_unidade(doc: Documento) -> None:
    for match in re.finditer(r"exerc[ií]cio(?:\s+de)?\s+(20\d{2})", doc.texto, re.IGNORECASE):
        _adicionar(doc, "exercicio", match.group(1), match.start(1), match.end(1), hipotese=False)
    for match in re.finditer(r"unidade gestora\s*:?\s*(\d{4,6})", doc.texto, re.IGNORECASE):
        _adicionar(doc, "unidade", match.group(1), match.start(1), match.end(1), hipotese=False)


def planilha_para_texto(linhas: list[list[str]]) -> str:
    if not linhas:
        return ""
    cabecalho = [_sem_acento(coluna).lower() for coluna in linhas[0]]
    ignorar = [
        indice
        for indice, nome in enumerate(cabecalho)
        if any(chave in nome for chave in ("nome do empregado", "cpf", "telefone", "endereco", "cep", "e-mail", "email"))
    ]
    blocos = []
    for numero, linha in enumerate(linhas[1:], start=2):
        pares = []
        for indice, celula in enumerate(linha):
            if indice in ignorar:
                continue
            valor = (celula or "").strip()
            if valor == "" or valor in {"0", "0,00", "0.00", "R$ 0,00"}:
                continue
            titulo = linhas[0][indice].strip() if indice < len(linhas[0]) else f"col{indice}"
            pares.append(f"{titulo}={valor}")
        if pares:
            blocos.append(f"linha {numero}: " + " | ".join(pares))
    return "\n".join(blocos)


class _TextoHtml(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.partes: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.partes.append(data.strip())


def html_para_texto(bruto: str) -> str:
    parser = _TextoHtml()
    parser.feed(bruto)
    return "\n".join(parser.partes)


def vaza_contato(texto: str) -> bool:
    return bool(TELEFONE_RE.search(texto) or CEP_RE.search(texto) or CPF_PONTUADO.search(texto) or CPF_MASCARADO.search(texto))
