"""PDF minimo com Helvetica, so para testes locais."""


def pdf_texto(texto: str | None) -> bytes:
    if texto:
        escaped = (
            texto.encode("latin-1", "replace")
            .replace(b"\\", b"\\\\")
            .replace(b"(", b"\\(")
            .replace(b")", b"\\)")
        )
        conteudo = b"BT /F1 11 Tf 50 780 Td (" + escaped + b") Tj ET"
    else:
        conteudo = b""
    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(conteudo) + conteudo + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    saida = bytearray(b"%PDF-1.4\n")
    xref = [0]
    for indice, objeto in enumerate(objetos, start=1):
        xref.append(len(saida))
        saida += f"{indice} 0 obj\n".encode() + objeto + b"\nendobj\n"
    posicao = len(saida)
    saida += f"xref\n0 {len(objetos) + 1}\n".encode()
    saida += b"0000000000 65535 f \n"
    for ponto in xref[1:]:
        saida += f"{ponto:010d} 00000 n \n".encode()
    saida += f"trailer << /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{posicao}\n%%EOF".encode()
    return bytes(saida)
