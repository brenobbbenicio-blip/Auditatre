# Auditatre

Ingestor e cruzamento documental do TRE-PA. A primeira entrega cataloga o que está em `inbox/drive`, cruza chaves públicas e aponta lacuna. Não há dashboard nem grafo de pessoas.

O programa não acessa a rede. Se o inbox não existir, ele para. O corpus fica de fora do git.

```bash
python -m auditatre --inbox inbox/drive --out out
```

Saídas em `out/`: `inventario.json`, `matriz.json`, `lacunas.json`, `manifesto.json` e `relatorio.md`.

Regras de leitura: zip até 3 níveis, com recusa de path traversal e zip bomb; deduplicação por sha256; PDF sem texto fica marcado, sem achado material; arquivo acima de 20 MB só é catalogado. Achado exige span. Vazio não vira zero. Apostila não abre contrato novo. Atesto de um polo não fecha os outros. Planilha é hipótese até um PDF confirmar o mesmo valor. Sanção só entra com CEIS, CNEP, acórdão ou sentença no corpus. O relatório não publica CPF nem classifica conduta.
