# Macaco

Estúdio desktop para Linux que transforma vídeos do YouTube em vídeos curtos verticais de curiosidades, para YouTube Shorts, Instagram Reels e TikTok. O tema é livre: você busca vídeos sobre o assunto que quiser ou acompanha canais. Três IAs fazem o trabalho:

- **Gemini (analista):** assiste ao vídeo pela URL e lista os momentos curiosos.
- **Roteirista (Gemini ou Claude):** reescreve cada momento com texto próprio e escreve título, descrição e hashtags. O padrão é o Gemini (mesma chave da análise). O Claude por API é opcional; sem chave, os botões “Escrever com o Claude (colar)” montam o pedido para você colar no chat do claude.ai e trazer a resposta de volta, validada pelo app.
- **Terceira IA (voz e legendas):** provedor ainda em aberto, atrás de uma interface trocável.

O app se chama Macaco (`APP_NAME` em `src/trinca/config.py`). O pacote Python, a pasta de dados (`~/.local/share/trinca`) e o item do cofre continuam com o nome interno `trinca`, para não perder dados e chaves já salvos. O logo é uma ilustração própria em SVG (`src/trinca/assets/macaco.svg`), no clima neon de pôr do sol de Vice City, sem arte oficial de jogo.

## Estado atual

Etapas 1 a 3 e 5 de 6 concluídas (a 4 só falta testar com a conta real). O app tem dois modos, escolhidos na tela Configurações:

- **Demonstração:** dados fictícios, nenhuma API é chamada. É o modo padrão.
- **Real:** o radar lê o YouTube sem chave (yt-dlp, só metadados), a análise usa o Gemini e os roteiros usam o Claude, com as suas chaves. O envio ao YouTube é feito pelo YouTube Studio, num Chrome controlado pelo app (Playwright), sem a API de envio. A voz usa o edge-tts (ou a sua gravação, alinhada com o Whisper local), as legendas e a montagem usam o FFmpeg, e o player toca o vídeo renderizado.

As integrações do modo real foram testadas com respostas simuladas e com chaves falsas contra os servidores reais. **Elas ainda não foram executadas com chaves válidas**; a primeira análise e o primeiro roteiro reais precisam ser conferidos.

| Etapa | Conteúdo | Estado |
|---|---|---|
| 1 | Esqueleto, nove telas e modo de demonstração | Concluída |
| 2 | Radar pela YouTube Data API, análise com o Gemini e roteiros com o Claude | Concluída, falta validar com chaves reais |
| 3 | Importação, narração, montagem com FFmpeg, legendas e player | Concluída |
| 4 | Publicação no YouTube e pacote para Instagram e TikTok | Pacote pronto; envio ao YouTube pelo navegador implementado, falta testar com a conta real |
| 5 | Empacotamento (.deb) | Concluída (`packaging/build-deb.sh`); AppImage não feito |
| 6 | Registro de canais autorizados | A fazer |

## Instalar (.deb)

```bash
packaging/build-deb.sh              # gera dist/macaco_0.1.0_all.deb
sudo apt install ./dist/macaco_0.1.0_all.deb
```

O pacote leva só o código; na instalação ele cria `/opt/macaco/venv` e baixa as dependências de `requirements.lock` (precisa de internet e leva alguns minutos). Depois o "Macaco" aparece no menu de aplicativos e o comando `macaco` abre o app. Para remover: `sudo apt remove macaco`.

## Como rodar (desenvolvimento)

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m trinca
```

Para o envio ao YouTube é preciso ter o Google Chrome instalado. Na primeira vez, o app abre uma janela do Chrome com um perfil próprio; entre na sua conta Google nela (o app nunca vê a senha). O login fica guardado nesse perfil, na pasta de dados do app. O envio automatiza a interface do YouTube Studio, o que não é um uso previsto pelos termos do YouTube e pode quebrar quando a interface mudar; nesse caso o vídeo fica como rascunho no Studio.

Testes:

```bash
.venv/bin/python -m pytest
```

O FFmpeg do sistema é usado se existir (`sudo apt install ffmpeg`); sem ele, o app usa o binário do pacote imageio-ffmpeg. No primeiro uso do Whisper, o modelo `base` (cerca de 150 MB) é baixado; se falhar, o app divide a sua gravação pelo tamanho dos textos. **Cortes de vídeos reais:** na Importação, "Baixar vídeo completo" baixa o vídeo de origem (até 1080p, no máximo 3 horas, reaproveitado se já existir) e ajusta o corte inicial para durar de 30 s a 1 min 30 s a partir da curiosidade. Escolha "Áudio original do vídeo" para manter o som original, sem narração nem legenda; o quadro 16:9 entra inteiro sobre um fundo desfocado em 9:16. Na Revisão você ajusta início e fim do corte. O vídeo final nunca passa de 90 s (limite fixo) e o app avisa abaixo de 30 s. O download não pede mais autorização do canal: o uso do conteúdo de terceiros é de responsabilidade de quem publica.

**Pastas dos vídeos:** por padrão ficam em `~/Vídeos/Macaco`: `brutos/` guarda os vídeos baixados do YouTube e `cortes/` os vídeos prontos (com a capa `.jpg` ao lado). A aba Biblioteca mostra, toca e exclui esses arquivos. Na primeira abertura desta versão, o app move a pasta antiga (`~/.local/share/trinca/saida`) para lá. Dá para trocar a pasta em Configurações.

**Busca para o público brasileiro:** no Radar, "Público: Brasil" faz a busca como um usuário brasileiro e só mantém vídeos em português (estimativa pelo título e pela descrição); "Tamanho do canal" descarta canais abaixo do número de inscritos escolhido, e "Maiores canais" ordena pelos inscritos.

A voz sintética (edge-tts) envia o texto de cada bloco ao serviço de voz da Microsoft, sem chave.

## Como usar o modo real

1. Crie a chave do Gemini no Google AI Studio (o YouTube não precisa de chave). A chave do Claude (Console da Anthropic, paga por uso) só é necessária se você escolher o Claude como roteirista em Configurações.
2. Abra Configurações, cole cada chave e clique em Salvar.
3. Clique em "Usar o modo real". O modo real tem um banco próprio e começa vazio.
4. No Radar, digite um tema e clique em "Buscar vídeos". Se preferir acompanhar canais, adicione um pelo @, pelo link ou pelo ID na aba "Canais monitorados".
5. Escolha um vídeo e clique em "Analisar com o Gemini".

Custos e limites que o app acompanha no Painel:

- **Radar (yt-dlp):** não usa cota nem chave. Se o YouTube mudar e a busca falhar, rode `pip install -U yt-dlp`. A busca lê até 30 resultados e filtra por duração, data e ordem no próprio app.
- **YouTube Data API (só no código legado, não usada):** 10.000 unidades por dia. Uma busca por tema gasta 101 unidades, adicionar um canal gasta 1 e cada verificação de canal gasta até 2. O radar para sozinho quando a cota do dia acaba, o que dá cerca de 99 buscas por tema por dia. A busca por tema é sempre manual; só os canais são verificados sozinhos.
- **Gemini:** a análise de vídeos do YouTube por URL está em prévia. No plano gratuito o limite é de 8 horas de vídeo por dia, e o app avisa antes de passar disso. Vídeos longos são analisados em partes de 20 minutos, um pedido por parte. Só vídeos públicos funcionam.
- **Claude:** um pedido por roteiro e um por conjunto de textos de publicação, cobrados na sua conta da Anthropic.

Os modelos padrão são `gemini-4-hydrogen` e `claude-opus-5-5`, conferidos na documentação em 16/11/2026. Os dois podem ser trocados em Configurações. Com o Claude, uma recusa por filtro de segurança é refeita automaticamente em outro modelo (`fallbacks`), nos modelos que aceitam esse recurso.

## Estrutura

```
src/trinca/
  config.py        constantes, caminhos e padrões
  security.py      validação de entradas, URLs e caminhos; ocultação de segredos
  credentials.py   chaves de API no cofre do sistema
  db.py            banco SQLite
  demo_data.py     dados fictícios do modo de demonstração (edite aqui)
  context.py       contexto compartilhado e carga inicial da demonstração
  tasks.py         tarefas em segundo plano com progresso e cancelamento
  pipeline/        radar, análise, roteiro, narração, montagem e publicação
                   (youtube_api.py lê dados da YouTube Data API; youtube_browser.py envia vídeos pelo YouTube Studio)
  ui/              janela principal, tema e as nove telas
tests/             testes de segurança, banco, integrações e fluxo pela interface
```

Cada etapa do pipeline tem um protocolo (por exemplo `VideoAnalyst`), uma implementação de demonstração e, quando já existe, uma implementação real (`YouTubeRadar`, `GeminiAnalyst`, `ClaudeWriter`). As telas não sabem qual das duas está em uso.

## Limites de conteúdo

- Cada vídeo de origem é usado uma única vez. Quando um roteiro usa curiosidades de um vídeo, as outras curiosidades dele ficam bloqueadas. Excluir um rascunho devolve o vídeo; depois de agendado ou publicado, ele fica usado em definitivo e as buscas não o trazem de novo.
- As imagens e o áudio do vídeo final vêm só de arquivos importados pelo usuário. O app não baixa vídeos dos canais monitorados.
- O roteiro conta as curiosidades com texto próprio e não resume o vídeo inteiro.
- Toda descrição precisa citar o canal e trazer o link do vídeo original. O app bloqueia a publicação e o pacote quando o link falta.
- Instagram e TikTok não são automatizados por navegador. O app monta o pacote e abre a página oficial de upload.
- Nada é publicado sem aprovação na tela de revisão.

## Segurança

- **Chaves de API:** ficam apenas no cofre do sistema (Secret Service, via `keyring`). O app recusa cofres em texto puro, limpa o campo depois de salvar e mostra só os quatro últimos caracteres.
- **Logs e mensagens de erro:** passam por um filtro que oculta chaves e tokens.
- **Respostas das IAs:** são tratadas como dados não confiáveis, porque um vídeo pode conter texto feito para manipular o modelo. Cada resposta passa por validação estrita de tipos, tamanhos, tempos e referências antes de entrar no banco, e os links são removidos. Os únicos links publicados são os de crédito, montados pelo app.
- **Chamadas às APIs:** só HTTPS com verificação de certificado. A chave do YouTube vai em cabeçalho, nunca na URL, e os redirecionamentos são recusados para ela não seguir a outro servidor. Os pedidos ao Gemini usam `store=False`, para o Google não guardar o pedido e a resposta para consulta.
- **O que sai da sua máquina:** para o Gemini, a URL pública do vídeo e o pedido de análise; para o Claude, as curiosidades escolhidas e o roteiro. Nenhum arquivo seu é enviado.
- **Banco:** consultas sempre com parâmetros, colunas de atualização em lista fixa, arquivo com permissão 0600 em pasta 0700.
- **Arquivos:** só extensões de mídia aceitas, caminhos absolutos e destinos confinados à pasta de saída.
- **Links:** o app só abre endereços https de uma lista fixa de sites.
- **Processos externos:** nenhum uso de shell. O FFmpeg é chamado com lista de argumentos, caminhos absolutos e confinados à pasta de saída (`videos/<id>-<título>/`).
- **Dependências:** quatro diretas (`PySide6-Essentials`, `keyring`, `anthropic` e `google-genai`), com todas as versões registradas em `requirements.lock` e sem vulnerabilidades conhecidas na auditoria de 16/11/2026.

Os bancos ficam em `~/.local/share/trinca/`: `demo.sqlite3` para a demonstração e `trinca.sqlite3` para o modo real. Os dados fictícios nunca se misturam aos reais.
