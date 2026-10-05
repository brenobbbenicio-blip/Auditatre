# Auditatre

Ingestor e cruzamento documental do TRE-PA, versão 0.1.0. A primeira entrega cataloga o que está em `inbox/drive`, cruza chaves públicas (CNPJ, contrato, nota de empenho e processo SEI) e aponta lacuna. Não há dashboard nem grafo de pessoas.

O programa não acessa a rede. Se o inbox não existir, ele para com código 2 e não busca documentos. O corpus e a saída ficam de fora do git (`inbox/` e `out/`).

## Instalação

Python 3.11 ou superior.

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Dependências de execução: `pypdf` e `openpyxl`. Testes: `pytest`. O comando `auditatre` fica disponível depois da instalação.

## Uso

```bash
python -m auditatre --inbox inbox/drive --out out
```

`--inbox` vale `inbox/drive` e `--out` vale `out` quando omitidos. Coloque o corpus na pasta do inbox antes de rodar.

A leitura aceita PDF, DOCX, XLSX, CSV, HTML, TXT e MD. Tipo desconhecido entra no inventário como catalogado, sem extração. PDF criptografado ou sem texto fica `sem_texto`, sem achado material.

## Saídas

Em `out/`:

- `inventario.json`: um registro por caminho (arquivo do inbox ou membro de zip), com `caminho`, `sha256`, `bytes`, `status`, `tipo`, `motivo` e `duplicata_de`.
- `matriz.json`: grupos cruzados. Cada fase guarda a própria lista de valores, com documento e span.
- `lacunas.json`: fase ausente, PDF sem texto, arquivo só catalogado, apostila sem contrato, polo em aberto ou planilha ainda não confirmada. O valor da lacuna fica `null`.
- `relatorio.md`: o mesmo cruzamento em texto.
- `manifesto.json`: sha256 das quatro saídas acima e dos arquivos do inbox. Membros internos de zip ficam de fora dessa lista.

Status do inventário: `extraido`, `duplicado`, `sem_texto`, `catalogado` e `zip_recusado`.

O diretório de saída também guarda `.pessoa_sal`. Esse sal produz `pessoa_ref` (HMAC-SHA256, 16 caracteres) quando um CPF válido aparece na mesma linha de um papel público. O CPF em si não é gravado.

## Regras

- Zip aberto com `zipfile`, no máximo 3 níveis. Recusa path traversal, zip criptografado e zip bomb: mais de 2000 membros, mais de 200 MB descompactados no total, razão de compressão acima de 100, ou membro acima desse teto. Membro interno acima de 20 MB só é catalogado. O caminho interno usa `arquivo.zip!/membro`.
- Deduplicação por sha256 entre arquivos que seriam lidos. A segunda cópia fica `duplicado` e não é extraída de novo.
- Arquivo acima de 20 MB só é catalogado.
- Achado exige span no texto de origem.
- Vazio não vira zero. Valor zero é descartado. As fases contrato, empenho, liquidação e pagamento não são somadas.
- Apostila marca o contrato já existente e não abre contrato novo. Sem o contrato no corpus, a lacuna fica registrada.
- Atesto de um polo não fecha os outros. Polos reconhecidos: Marabá, Santarém e Belém.
- Planilha é hipótese até um PDF confirmar o mesmo valor na mesma fase. Colunas de nome de empregado, CPF, telefone, endereço, CEP e e-mail não entram no texto da planilha.
- Pessoas só entram com papel público na mesma linha: ordenador, fiscal, pregoeiro, atestante, beneficiário de diárias, ou nome em folha de servidores. Nome igual não liga pessoa a sanção.
- Sanção só entra com CEIS, CNEP, acórdão ou sentença no corpus, e só no CNPJ desse documento. Certidão entra como ato, sem preencher sanção.
- O relatório não publica CPF, telefone nem CEP, e recusa os termos fraude, improbidade, culpado e culpada.

## Cruzamento

O grupo usa, nesta ordem, CNPJ do fornecedor com número de contrato, só o contrato, CNPJ com nota de empenho, só a nota de empenho, só o CNPJ, processo SEI, ou o caminho do documento. Contrato, nota de empenho e SEI saem em forma canônica (`41/2025`, `2025NE000511`, processo SEI completo).

## Testes

```bash
python -m pytest
```

Cobrem zip, deduplicação, PDF sem texto, limite de tamanho, fases, apostila, polo, planilha, sanção, ausência de CPF no relatório e a parada sem inbox. Os testes não acessam a rede.

## Layout

- `src/auditatre/cli.py` para se o inbox não existir.
- `src/auditatre/run.py` percorre a pasta e grava as saídas.
- `src/auditatre/leitura.py` lê PDF, DOCX, planilha, CSV e HTML.
- `src/auditatre/extract.py` extrai chaves e papéis. Endereço e telefone ficam de fora. CPF só vira `pessoa_ref`.
- `src/auditatre/crosswalk.py` monta a matriz e as lacunas, sem somar fases.
- `src/auditatre/zipsafe.py` abre o zip e aplica os limites.
- `src/auditatre/report.py` escreve o relatório e recusa dado pessoal e juízo de conduta.
