# CGTN Español runtime

Esta branch publica a fonte oficial renovada e o estado consumido pelo
relay de áudio. `cgtn-es.m3u8` é a fonte de descoberta/fallback; ela não
é, por si só, um transcode.

`test/playlist.m3u8` é uma amostra curta realmente normalizada pelo
mesmo pipeline do relay: vídeo H.264 em copy, áudio reencodificado para
AAC-LC 48 kHz estéreo a 128 kb/s e saída MPEG-TS remuxada.

Quando a variável de repositório `CGTN_RELAY_PUBLIC_URL` estiver
configurada, as playlists principais passam automaticamente a apontar
para o HLS normalizado contínuo.
