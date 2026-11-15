# Auditoría del doblaje de Syberia

Se revisó la edición Steam 8987614 con el parche castellano instalado. Se verificaron los hashes de los 674 archivos de audio del parche y se analizaron 336 grabaciones únicas conservadas con metadatos de voz o ambiente vocal.

## Voces ambientales

La primera revisión detectó 60 pistas con habla reconocible y un evento de ambiente asociado en los bancos de los capítulos 1, 2, 4, 6 y 7. Algunas pistas reutilizan la misma grabación o fragmentos de una conversación.

- **Capítulo 1.** Comentarios del público en el concierto y voces de fondo en la mina.
- **Capítulo 2.** Tres grabaciones de conversación vinculadas a `Chap2_Amb_3D_RoomDial`.
- **Capítulo 4.** Conversaciones de fondo en `Chap_4_Amb_3D_Chatters`.
- **Capítulo 6.** Conversaciones de la cafetería y del distrito de los músicos. Tres pistas de cafetería contienen diálogos de más de un minuto cada una.
- **Capítulo 7.** Voces de fondo, incluido un grito comprensible vinculado al gestor de ambiente del capítulo.

El inventario incluye el medio Wwise, el banco, los eventos y fragmentos de la transcripción automática. [Pistas ambientales detectadas](/D:/GameSpanishVoices/work/syberia/analysis/audio-restante/voces-ambientales-detectadas.csv)

La revisión por idioma identificó «Garçon !» en una conversación de la cafetería y en su versión corta, y «On y va» en dos copias de una grabación de la mina. La cafetería usa «¡Camarero!» en castellano. La grabación de «On y va» se conserva en francés tanto en la mina como en el ambiente del menú. Las conversaciones de ambiente en inglés que coinciden en los bancos inglés y francés usan la misma grabación. La mezcla conserva el fondo obtenido de cada original.

La segunda pasada también identificó cuatro recortes del público del concierto y un «Come on!» de la mina. Se añadieron al inventario de la actualización. Algunos recortes llevan la misma voz que su conversación completa.

La actualización incluye 66 pistas de ambiente dobladas, dos frases de Kate y un arrullo usado por tres eventos. El instalador comprueba 676 archivos de audio contra el manifiesto del parche.

El parche anterior rellenaba los finales de los WEM para mantener el tamaño de los archivos ingleses. El motor Wwise del juego cargaba los bancos, pero terminaba las voces de inmediato. La corrección conserva los datos de audio y reconstruye los índices de los bancos con los tamaños reales. Se probó la reproducción de voces empotradas y transmitidas con el motor 2019.1.6 de la edición Steam.

## Frases y efectos vocales

| Escena | Hallazgo |
| --- | --- |
| Capítulo 5, retrato del padre de Kate | El medio `249979296` corresponde al subtítulo `DFr_E9B9461F`, sobre las fotos que esconde su madre. El banco lo publica como `DLG_DFr_67A1B49B`. |
| Capítulo 9, cerradura de la boca del autómata | El medio `146210980` corresponde a la pista `DFr_3D5E0ED2`, sobre cómo colocar la llave. El banco lo publica como `DLG_DFr_21DBD63B`. |
| Capítulo 7, escena de Óscar con la paloma | Tres eventos apuntan a copias idénticas de una voz que dice «cooing interrogatively». Dos modelos reconocieron esas palabras. El juego también incluye arrullos en pistas separadas. |

Las dos frases de Kate tienen subtítulo y grabación original con identificadores distintos. La actualización enlaza las grabaciones dobladas a los identificadores que el juego busca para esos subtítulos. El motor de audio confirmó ambos enlaces al seleccionar Español. Su reproducción en partida queda sin verificar.

La pista de Dana sobre llamar a Londres que aparece duplicada en el capítulo 5 tiene su evento válido y doblado en el capítulo 9. El evento de la fecha del 23 de agosto de 2003 tiene una variante doblada y otra vacía. El evento «¡Leon! ¡Soldados!» apunta a un objeto que no figura en los bancos de ningún idioma.

## Vídeos y archivos internos de Unity

La revisión de «Anteriormente» cubrió sus 38 intervenciones y examinó el audio inglés que podía quedar entre ellas o mezclado con el fondo. No se detectaron frases inglesas adicionales inteligibles. Los dos vídeos de logotipo carecen de habla detectada. Los 81 clips internos de Unity se asociaron a pistas sin salida de audio asignada que el juego silencia.

La comprobación combinó transcripción automática, contraste entre bancos y pruebas de carga con el motor de audio del juego. El volumen de las voces ambientales depende de la escena y de la mezcla activa. Quedan fuera del recuento las pistas con transcripciones inestables, entre ellas el audio de fondo de dos secuencias del capítulo 9. Los bancos y sus eventos se inspeccionaron con wwiser. [Documentación de wwiser](https://github.com/bnnm/wwiser)
