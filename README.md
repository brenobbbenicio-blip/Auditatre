# Auditatre

Ingestor e cruzamento documental do TRE-PA, versão 0.1.0. A primeira entrega cataloga o que está em `inbox/drive`, cruza chaves públicas (CNPJ, contrato, nota de empenho e processo SEI) e aponta lacuna. Não há dashboard nem grafo de pessoas.

O modo padrão é offline. Sem `--drive-folder`, o programa não acessa a rede; se o inbox não existir, ele para com código 2 e não busca documentos. A importação opcional do Google Drive materializa uma pasta escolhida antes da ingestão. O corpus e a saída ficam de fora do git (`inbox/` e `out/`).

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

## Importação opcional do Google Drive

Instale as dependências opcionais apenas se for usar a importação:

```bash
.venv/bin/pip install -e ".[dev,drive]"
```

O importador usa a API Drive v3 e Application Default Credentials (ADC), com escopo `https://www.googleapis.com/auth/drive.readonly`. A API Drive deve estar habilitada no projeto Google Cloud; a identidade autenticada deve ter acesso à pasta e permissão de download. O compartilhamento de um link não substitui a autenticação da API. A sessão Google Drive conectada ao ChatGPT não fornece credenciais ao programa.

Para uma conta de serviço, compartilhe a pasta com seu e-mail e configure `GOOGLE_APPLICATION_CREDENTIALS` com o caminho de um JSON guardado **fora do checkout**. ADC de usuário também pode ser configurado externamente com autorização de leitura do Drive. O programa não solicita login, não cria tokens e não grava credenciais. Não copie credenciais para o inbox ou para o repositório.

```bash
# Importa a pasta escolhida e, somente se a importação completar, ingere o corpus.
python -m auditatre \
  --drive-folder 1lgbIq4BL2JUrDaBi1ZwMAmt6nBxC4aPz \
  --inbox inbox/drive --out out

# Materializa e confere a importação, sem produzir o cruzamento.
python -m auditatre \
  --drive-folder 1lgbIq4BL2JUrDaBi1ZwMAmt6nBxC4aPz \
  --inbox inbox/drive --import-only

# Depois da importação, este comando usa somente os bytes locais.
python -m auditatre --inbox inbox/drive --out out
```

O ID deve ser o da pasta, sem URL. Um inbox gerenciado aceita uma única pasta raiz; para importar outra pasta, escolha outro inbox ignorado pelo Git ou fora do checkout. Arquivos manuais no inbox continuam sendo lidos. O importador recusa inbox com arquivos rastreados pelo Git ou sem regra de exclusão, e recusa links simbólicos em seus caminhos de escrita.

### Formatos e alcance

| Origem | Materialização |
| --- | --- |
| PDF, XLSX, DOCX, CSV, HTML, TXT, MD, ZIP e outros arquivos binários | Download dos bytes originais; tipos desconhecidos continuam apenas catalogados |
| Google Docs | DOCX |
| Google Sheets | XLSX com todas as abas, em vez de CSV que exportaria só a primeira |
| Google Slides | PDF |
| Google Drawings | PDF |
| Outros formatos Google e atalhos | Pendência explícita, sem seguir o alvo do atalho |

A listagem é paginada e recursiva, apenas nos descendentes da pasta escolhida, incluindo pastas em drives compartilhados acessíveis à identidade. Não pesquisa o Drive inteiro, não raspa páginas e não modifica arquivos remotos. A listagem da API compreende os itens visíveis à identidade: uma conclusão bem-sucedida não prova acesso a itens ocultos por permissões. ZIPs são baixados intactos; a extração posterior conserva os limites e recusas do ingestor.

Referências oficiais: [download e exportação](https://developers.google.com/workspace/drive/api/guides/manage-downloads), [formatos de exportação](https://developers.google.com/workspace/drive/api/guides/ref-export-formats), [listagem paginada](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/list). A API `files.export` limita cada exportação Google a 10 MB; exceder esse limite gera pendência, sem criar uma cópia truncada.

### Proveniência, atualização e falhas

Os objetos ficam em `inbox/drive/.auditatre-drive/objects/<sha256>.<extensão>`. Os nomes remotos são metadados: nunca são usados como caminhos locais de escrita, evitando colisões de nomes e path traversal. Cópias com bytes e formato iguais compartilham um objeto, mantendo os registros de todos os IDs e caminhos do Drive. Mesmo hash com extensões distintas mantém representações separadas para a leitura correta; o ingestor aplica sua deduplicação por hash.

`inbox/drive/.auditatre-drive/manifesto.json` registra:

- Pasta raiz, data UTC da importação e indicador `completo`.
- `drive_id`, `caminho_drive`, `caminhos_drive`, `modified_time`, `version` e MIME de cada arquivo observado.
- `materializado`: caminho local, SHA-256, tamanho, data/versão da origem efetivamente baixada e MIME de exportação.
- Status `baixado`, `reutilizado`, `falha`, `nao_suportado` ou `nao_observado`; código de erro e `duplicata_de` quando aplicável.

O manifesto é trocado atomicamente depois dos downloads. Um arquivo sem mudança de data/versão/MIME só é reutilizado se tamanho e SHA-256 locais conferirem. Atualizações recebem novos objetos; versões antigas não entram na ingestão atual. A versão remota é conferida novamente depois do download, junto com tamanho e MD5 quando disponíveis para arquivos binários. Há no máximo três tentativas para HTTP 429 e falhas transitórias 5xx antes de iniciar a leitura do corpo; streams interrompidos não são concatenados nem publicados.

Falhas parciais salvam as cópias bem-sucedidas e preservam a última cópia válida dos arquivos que falharam. A data observada da atualização fica separada da data dos bytes anteriores. A CLI retorna **3 e não executa a ingestão** quando há pendência. Se você executar posteriormente o comando offline sobre esse estado parcial, ele processa as últimas cópias disponíveis, com a pendência registrada em `lacunas.json` e no manifesto de saída. Não trata a cópia antiga como versão recém-baixada.

Uma listagem completa que já não encontra um arquivo o marca como inativo; seus bytes são preservados, mas não ingeridos. Em falha de listagem, registros anteriores não observados continuam ativos e a importação fica incompleta. Acesso negado à pasta raiz, manifesto inválido ou falha em sua gravação não substituem o manifesto anterior. Objetos históricos e downloads órfãos não são apagados automaticamente nem ingeridos: só objetos referenciados e ativos participam da leitura.

Por padrão, há limites de 200 MiB por download, 1 GiB de bytes recebidos por execução, 10.000 itens listados e 50 níveis de pastas. `--drive-max-file-bytes` e `--drive-max-total-bytes` ajustam os dois primeiros em bytes. **A ingestão continua apenas catalogando arquivos acima de 20 MB**, mesmo que importados. Importações concorrentes no mesmo inbox são recusadas. Se o processo for interrompido abruptamente, confira que não há importação ativa antes de remover o arquivo `.auditatre-drive/.import.lock` deixado para trás.

Antes da leitura, o ingestor verifica os objetos ativos contra o manifesto. Objeto ausente, hash divergente ou caminho inválido interrompe a ingestão com código 3; uma nova importação pode recuperar bytes corrompidos. O modo offline não carrega dependências Google nem abre uma sessão de rede.

## Saídas

Em `out/`:

- `inventario.json`: um registro por caminho (arquivo do inbox ou membro de zip), com `caminho`, `sha256`, `bytes`, `status`, `tipo`, `motivo` e `duplicata_de`.
- `matriz.json`: `organizacoes`, `atos` e `vinculos`. Cada fase guarda a própria lista de valores, com documento e span, no ato que a documenta.
- `lacunas.json`: fase ausente, PDF sem texto, arquivo só catalogado, apostila sem contrato, polo em aberto ou planilha ainda não confirmada. O valor da lacuna fica `null`.
- `relatorio.md`: o mesmo cruzamento em texto.
- `manifesto.json`: sha256 das quatro saídas acima e dos arquivos do inbox. Membros internos de zip ficam de fora dessa lista.

Quando o inbox contém uma importação, o inventário e as entradas do manifesto recebem `drive`, com todos os registros de origem associados aos bytes (também nos membros de ZIP, via arquivo externo). O manifesto de saída guarda o estado completo em `importacao_drive`. Metadados, locks, downloads temporários e objetos históricos não são catalogados como documentos.

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
- Sanção só entra com penalidade, destinatário e ato no mesmo bloco de CEIS, CNEP, acórdão ou sentença. CNPJ citado em sentença ou acórdão, sem penalidade, não vira sanção. Processo e decisão ficam em listas próprias. Datas e alcance só entram quando o texto os rotula, e mais de uma data documentada é mantida. Várias sanções são acumuladas. Certidão entra como ato, sem preencher sanção.
- O relatório não publica CPF, telefone nem CEP, e recusa os termos fraude, improbidade, culpado e culpada.

## Cruzamento

Organização, ato e vínculo são registros separados. A chave do ato junta órgão/unidade, exercício e identificador (`ato:contrato|ug:150001|exercicio:2024|id:10/2024`). Sem unidade no texto, a chave usa `ug:ausente` e não se mistura com uma unidade informada. Contrato, nota de empenho e SEI saem em forma canônica (`41/2025`, `2025NE000511`, processo SEI completo).

O vínculo `confirmado` exige o mesmo identificador nos dois documentos, com unidade compatível (igual ou ausente nos dois lados) e as duas evidências. `candidato` registra CNPJ comum ou referência incompleta e não copia pagamento, empenho ou liquidação para o contrato. `conflito` cobre unidade divergente, vários alvos para o mesmo identificador, ou vários CNPJs e contratos no mesmo texto sem par na mesma linha. Um documento com um único CNPJ e um único contrato pareia os dois. CNPJ do órgão (contratante ou UG emitente) não vira fornecedor.

## Testes

```bash
python -m pytest
```

Cobrem zip, deduplicação, PDF sem texto, limite de tamanho, fases, apostila, polo, planilha, sanção, ausência de CPF no relatório e a parada sem inbox. Também cobrem CNPJ comum, nota de empenho sem referência contratual, unidades distintas, combinação sem pareamento, sentença sem penalidade, acórdão que só cita empresa e sanções múltiplas. A suíte Drive usa dados e transporte fictícios para recursão, paginação, exportação, duplicatas, atualizações, falhas parciais, corrupção, limites, caminhos hostis e preservação do modo offline. Os testes não acessam a rede nem precisam de credenciais Google.

## Layout

- `src/auditatre/cli.py` seleciona importação explícita ou modo offline e para se o inbox não existir.
- `src/auditatre/drive_api.py` isola autenticação e GETs da API Drive, com dependências opcionais.
- `src/auditatre/drive_import.py` materializa objetos e manifesto local e valida a proveniência sem rede.
- `src/auditatre/run.py` percorre a pasta e grava as saídas.
- `src/auditatre/leitura.py` lê PDF, DOCX, planilha, CSV e HTML.
- `src/auditatre/extract.py` extrai chaves e papéis. Endereço e telefone ficam de fora. CPF só vira `pessoa_ref`.
- `src/auditatre/crosswalk.py` separa organização, ato e vínculo e monta as lacunas, sem somar fases.
- `src/auditatre/zipsafe.py` abre o zip e aplica os limites.
- `src/auditatre/report.py` escreve o relatório e recusa dado pessoal e juízo de conduta.
