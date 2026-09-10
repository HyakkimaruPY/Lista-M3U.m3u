# Old HLS

`old_hls.m3u8` e a grade remota do player legado da TV Philco. A TV baixa esta lista do GitHub ao abrir a area de TV; trocar, remover ou adicionar um canal nao exige gerar um novo `.bin`.

## Categorias

Desde a V7.3.2 DYNCAT, as categorias nao sao fixas no firmware. A interface descobre automaticamente os valores distintos de `group-title` presentes na playlist. Portanto, criar, renomear ou remover uma categoria e somente uma alteracao no M3U.

Grupos atuais: `Variedade`, `Filmes`, `Séries`, `CCTV` e `Beta`. `Beta` e apenas uma separacao editorial para testes; tecnicamente os canais passam pelo mesmo AUTOHLS dos demais.

## Regra principal: o M3U nao descreve o tratamento tecnico

A partir da V7.3.5 AUTOHLS, nao usamos `x-profile`, hostname de provedor ou outra tag privada para dizer ao player como tratar um canal. O player inspeciona o HLS real e classifica automaticamente o media playlist.

Perfis detectados por recursos:

- `simple`: MPEG-TS claro/classico; proxy progressivo.
- `normalize`: existem tags que podem confundir o parser legado, como `EXT-X-DISCONTINUITY-SEQUENCE`, `EXT-X-MEDIA-SEGMENT-*`, CUE/SCTE ou bookkeeping semelhante; a bridge entrega uma visao HLS v3 minima preservando temporizacao, sequencia, `EXTINF`, discontinuities reais e segmentos.
- `aes128`: HLS `METHOD=AES-128` com `KEYFORMAT=identity`; a bridge busca chave/IV, faz AES-128-CBC e entrega MPEG-TS em claro ao player antigo.
- `normalize+aes128`: aplica as duas adaptacoes anteriores.
- `unsupported`: recurso ainda nao comprovado no hardware atual. Hoje entram aqui CMAF/fMP4 (`EXT-X-MAP`/`.m4s`), media BYTERANGE, SAMPLE-AES, KEYFORMAT nao-identity e DRM moderno.

Essa deteccao e por caracteristica do manifesto/segmento, nao por marca. Um provedor novo com a mesma estrutura AES-128 classica recebe automaticamente o mesmo tratamento que o Pluto; um canal novo com bookkeeping semelhante ao Novelissima recebe automaticamente normalizacao, sem alterar o M3U ou o firmware.

## Perfil de fonte aceito

- Extended M3U em UTF-8 (`.m3u8`).
- Uma entrada = `#EXTINF` + URL HTTP/HTTPS.
- `group-title` e obrigatorio, mas o nome da categoria e dinamico.
- Query strings sao permitidas quando fazem parte da URL funcional. Elas nao sao motivo de rejeicao por si so.
- Headers externos no formato `url|User-Agent=...` continuam proibidos: a entrada deve ser autocontida para o player remoto.
- O alvo preferencial continua H.264/AVC + AAC em MPEG-TS ate 1080p/60 fps, com 720p tentado primeiro.
- Widevine, PlayReady, FairPlay, SAMPLE-AES, HEVC/H.265, AV1, VP9, AC-3/E-AC-3, CMAF/fMP4 e outros perfis nao implementados nao entram ate existir tratamento comprovado e teste correspondente.

## O validador espelha o player

`scripts/hls_compat.py` e a especificacao executavel do comportamento AUTOHLS no CI. `scripts/validate_old_hls.py` usa esse modulo antes de aceitar a lista.

O gate faz a mesma sequencia conceitual da TV:

1. abre a URL e segue no maximo 8 redirects;
2. mantem cookies da sessao e resolve URLs relativas;
3. escolhe uma variante H.264/AAC, tentando ate 720p antes do fallback ate 1080p;
4. inspeciona o media playlist e detecta `simple`, `normalize`, `aes128`, `normalize+aes128` ou `unsupported`;
5. simula a normalizacao HLS v3 quando necessaria;
6. para AES-128/identity, baixa chave e segmento, executa AES-128-CBC de verdade e exige sync MPEG-TS no resultado;
7. depois executa `ffprobe`/`ffmpeg` para confirmar audio e video decodificaveis.

Assim, um canal nao e recusado apenas por ser mais complexo. Se a bridge sabe transforma-lo e a CI consegue reproduzir a mesma transformacao, ele e `compatible`. Se aparecer um recurso que o player ainda nao trata, ele e `incompatible`. Timeout, DNS, geoblock ou erro momentaneo continuam `uncertain` para evitar remocao destrutiva por problema do runner.

## Admissao de novos canais

Ao propor um canal novo, nao crie perfil manual. Coloque somente `#EXTINF`, `group-title` e a URL. O CI decide pelo HLS observado naquele momento. Para entrar na grade estavel, o candidato deve:

- passar os testes unitarios do classificador;
- nao cair em `unsupported`;
- passar a adaptacao AUTOHLS correspondente;
- se AES-128, descriptografar para MPEG-TS valido;
- passar a bateria A/V do `ffprobe`/`ffmpeg`.

A categoria `Beta` pode continuar sendo usada para organizar testes fisicos, mas ela nao ignora uma incompatibilidade tecnica comprovada.

## CCTV

A categoria CCTV foi preenchida a partir de fontes gratuitas/diretas da `cn.m3u`. A bateria inicial aprovou CCTV-1, 2, 3, CCTV-4 Asia e Europa, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15 e 17. CCTV-16 e CCTV-4 America ficaram de fora quando os endpoints observados falharam no gate real.

## URL consumida pelo player

`https://raw.githubusercontent.com/HyakkimaruPY/Lista-M3U.m3u/main/old_hls.m3u8`

O QJY antigo nao acessa o GitHub diretamente. A bridge moderna faz HTTPS/TLS/DNS, interpreta o M3U e entrega a grade localmente em `http://127.0.0.1:8765/c`.

## Bateria de testes

1. `tests/test_old_hls.py`: regressao do classificador AUTOHLS, categorias dinamicas e regras de entrada.
2. `scripts/validate_old_hls.py`: gate de compatibilidade real com a mesma semantica do player.
3. `scripts/validate_streams.py`: prova A/V com `ffprobe`/`ffmpeg`.
4. `scripts/probe_legacy_media.py`: diagnostico detalhado para investigar novos padroes quando necessario.

A regra de regressao e simples: primeiro provar o novo tratamento no player e no validador; somente depois ampliar o conjunto considerado compativel.
