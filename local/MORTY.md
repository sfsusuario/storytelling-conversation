# Personaje 2 — Adolescente ansioso (mirada derecha)

Ocho prompts completos para generar el clip de este personaje en cada
escena: un **video corto en bucle** listo para chroma-key y composición
junto al del otro personaje ([RICK.md](RICK.md)). Cada prompt asume que
adjuntas una imagen de referencia del personaje al generador — no describe
su apariencia física, solo la actuación de la escena. Es un arquetipo
original (adolescente nervioso), sin nombre ni referencia a ninguna obra
existente, para evitar bloqueos de los generadores por IP de terceros.

**Constantes en las 8 (no cambian con la emoción):**
- Fondo chroma verde uniforme, formato vertical 9:16, plano medio centrado.
- Loop perfecto y corto — el último frame conecta con el primero sin salto.
- Sin audio — el audio real lo pone el TTS por separado en el pipeline.
- Boca siempre en movimiento durante todo el bucle, nunca cerrada ni en reposo.
- Mirada siempre fija hacia la DERECHA del cuadro, nunca a cámara.
- Un solo personaje en cuadro, siempre — el otro se compone después en edición.

Si Gemini sigue rechazando la generación con un mensaje genérico ("no
puedo generar ese vídeo"), probá redactar el prompt como una descripción
de escena corrida, en un par de frases naturales, en vez de una lista de
requisitos técnicos encadenados — cuantas más condiciones y negaciones se
amontonan en una sola oración, más se parece a un intento de forzar al
modelo, y eso dispara el filtro con más facilidad.

---

## 1. Enojo / Ira

**Prompt:** Es un video corto y vertical, en bucle, sin sonido, del
personaje de la imagen de referencia. Está molesto pero se contiene:
habla con firmeza, alzando apenas la voz a mitad de una frase, con las
cejas hundidas y un gesto marcado de la mano hacia su derecha, los
hombros hacia adelante por la tensión. No deja de mover la boca en
ningún momento del bucle, como si estuviera hablando todo el tiempo. El
plano es medio y centrado, con un fondo verde parejo para chroma, y la
mirada se queda siempre fija hacia la derecha, nunca a cámara — en
cuadro no hay nadie más que él.

## 2. Miedo / Pánico

**Prompt:** Video corto y vertical, en bucle, mudo, del personaje de la
referencia. Está aterrado: habla entrecortado, a media palabra, con los
ojos como platos y las manos subidas hasta el pecho, como si quisiera
protegerse, el cuerpo echado hacia atrás. La boca sigue en movimiento
todo el bucle, sin quedarse quieta un instante. Plano medio y centrado,
fondo chroma verde, mirando siempre hacia la derecha, nunca a cámara,
solo él en cuadro.

## 3. Alegría / Euforia

**Prompt:** Video corto en bucle, vertical, sin audio, del personaje de
la imagen adjunta, eufórico. Habla con una sonrisa amplia, casi gritando
de la emoción, las cejas arriba, los brazos abiertos o un puño
celebrando en alto, el cuerpo inclinado hacia adelante por las ganas. La
boca no para de moverse en todo el loop. Plano medio y centrado, fondo
verde parejo, mirada fija siempre hacia la derecha, nunca a cámara, sin
nadie más en cuadro.

## 4. Tristeza / Decepción

**Prompt:** Loop corto y vertical, mudo, del personaje de referencia.
Habla bajito y desanimado, apenas moviendo la boca pero sin dejar de
hacerlo nunca; las comisuras caídas, la mirada de lado o hacia abajo, los
hombros hundidos, una mano sosteniéndose el propio brazo. Plano medio y
centrado, fondo chroma verde, mirando siempre hacia la derecha, nunca a
cámara, solo él en pantalla.

## 5. Sorpresa / Shock

**Prompt:** Video en bucle, vertical, sin sonido, del personaje de la
referencia, en shock. La boca se abre de golpe a mitad de una
exclamación corta, las cejas se disparan hacia arriba, el cuerpo se va
hacia atrás en un respingo y una mano sube a medio camino hacia la cara.
Sigue moviendo la boca durante todo el bucle. Plano medio y centrado,
fondo verde parejo, mirada siempre hacia la derecha, nunca a cámara,
nadie más en cuadro.

## 6. Asco / Desprecio

**Prompt:** Loop vertical, mudo, del personaje de la imagen de
referencia, hablando con desdén. La boca se le tuerce a un lado a media
palabra, como mascullando algo; un ojo entrecerrado, la cabeza
ligeramente ladeada, los brazos cruzados. No deja de mover la boca en
ningún momento. Plano medio y centrado, fondo chroma verde, mirando
siempre hacia la derecha, nunca a cámara, solo él en el cuadro.

## 7. Anticipación / Ansiedad

**Prompt:** Video corto en bucle, vertical, sin audio, del personaje de
la referencia. Habla rápido, a mitad de frase, como si estuviera
calculando lo que viene: mirada fija hacia adelante, las manos a medio
gesto contando posibilidades, el cuerpo inclinado hacia adelante. La
boca se mantiene en movimiento todo el loop. Plano medio y centrado,
fondo verde parejo, mirando siempre hacia la derecha, nunca a cámara,
sin nadie más en cuadro.

## 8. Confianza / Orgullo

**Prompt:** Loop corto y vertical, mudo, del personaje de la imagen
adjunta. Habla con total seguridad, a media afirmación, casi con una
sonrisa de lado; la barbilla un poco elevada, la postura erguida y
expandida, las manos en la cintura o gesticulando con calma. La boca
sigue en movimiento durante todo el bucle. Plano medio y centrado, fondo
chroma verde, mirando siempre hacia la derecha, nunca a cámara, solo
él en pantalla.
