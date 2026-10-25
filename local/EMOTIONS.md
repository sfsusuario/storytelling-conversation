# Emociones núcleo para diálogos dinámicos entre 2 personajes

Set de 8 emociones base (inspirado en la rueda de Plutchik, adaptado a
diálogo corto entre dúo cómico tipo "genio arrogante / ayudante ansioso")
para cubrir cualquier narración de video corto.
Cada una trae un **prompt listo para usar** como guía de generación de texto
(tono, vocabulario, ritmo, muletillas), en el mismo espíritu que el campo
`register` de `Persona` en [config.py](src/escalator/config.py), más un
**Gesto** con la dirección física para la imagen/animación de esa escena.

**Regla no negociable — boca siempre en movimiento:** el video muestra al
personaje TODO el tiempo mientras suena su audio narrado, de principio a fin
de cada línea. Por eso, en absolutamente todas las escenas, sin excepción y
sin importar la emoción, la boca debe estar a media articulación —
entreabierta o abierta, en pleno gesto de pronunciar una palabra— como si la
imagen fuera un fotograma congelado a mitad de una frase hablada. Nunca boca
cerrada, nunca gesto neutro de reposo, nunca una expresión "posada" de foto
fija: el personaje está hablando en este instante, siempre. Esto va primero,
antes que cualquier otro detalle de la emoción.

---

## 1. Enojo / Ira

**Prompt:**
> Habla con enojo creciente: frases cortas y cortantes, interrupciones,
> preguntas retóricas acusatorias ("¿en serio me estás diciendo esto?").
> Volumen implícito alto — usa mayúsculas puntuales o signos de exclamación
> dobles con moderación. Vocabulario directo, sin rodeos, algo de sarcasmo
> hiriente. El personaje busca imponerse o descargar frustración, no razonar.

**Gesto:** boca SIEMPRE en movimiento, abierta a mitad de un grito, como
congelada en pleno vocablo — nunca cerrada. Además: cejas fruncidas y hacia
abajo; un dedo o puño señalando al otro personaje; hombros tensos hacia
adelante.

## 2. Miedo / Pánico

**Prompt:**
> Habla con miedo o pánico creciente: frases entrecortadas, repeticiones
> nerviosas ("no, no, no esto no está pasando"), preguntas apresuradas,
> muletillas de duda ("¿y si...?", "espera, espera"). El ritmo se acelera,
> las oraciones se acortan a medida que sube la tensión. Puede haber
> negación inicial seguida de aceptación aterrada.

**Gesto:** boca SIEMPRE en movimiento, entreabierta y tensa, a mitad de una
palabra entrecortada — nunca cerrada. Además: ojos muy abiertos; manos
levantadas a la altura del pecho o cubriéndose parcialmente la cara; cuerpo
echado hacia atrás.

## 3. Alegría / Euforia

**Prompt:**
> Habla con entusiasmo desbordante: frases exclamativas, superlativos
> ("¡esto es lo mejor que me ha pasado en la vida!"), ritmo rápido y
> atropellado por la emoción, tendencia a interrumpirse a sí mismo con
> nuevas ideas. Optimismo contagioso, poca autocrítica, celebra en voz alta
> hasta los detalles pequeños.

**Gesto:** boca SIEMPRE en movimiento, bien abierta a media sonrisa hablada,
como en plena exclamación — nunca cerrada. Además: cejas levantadas; brazos
abiertos o un puño de celebración en alto; postura erguida e inclinada hacia
adelante por el entusiasmo.

## 4. Tristeza / Decepción

**Prompt:**
> Habla con desánimo: frases más cortas de lo normal, pausas implícitas
> (puntos suspensivos), tono resignado más que dramático. Poco volumen
> verbal — el personaje minimiza lo que siente ("no importa", "da igual,
> ya qué"). Puede haber autocompasión leve o nostalgia por algo perdido.

**Gesto:** boca SIEMPRE en movimiento aunque sea sutil, entreabierta hablando
en voz baja — nunca cerrada del todo. Además: comisuras caídas; mirada hacia
abajo o de lado; hombros hundidos; manos quietas o sosteniéndose el propio
brazo.

## 5. Sorpresa / Shock

**Prompt:**
> Habla con incredulidad inmediata: la primera reacción es una interjección
> corta ("¿QUÉ?", "no puede ser"), seguida de preguntas para confirmar lo
> que acaba de pasar ("espera, ¿estás diciendo que...?"). El personaje
> necesita reprocesar la información en voz alta antes de reaccionar del
> todo — frases fragmentadas mientras conecta ideas.

**Gesto:** boca SIEMPRE en movimiento, muy abierta a mitad de una exclamación
corta — nunca cerrada. Además: cejas levantadas al máximo; cuerpo echado
hacia atrás en un respingo; una mano puede estar a medio camino hacia la
cara o el pecho.

## 6. Asco / Desprecio

**Prompt:**
> Habla con desdén: comentarios cortos y despectivos, comparaciones
> degradantes, tono de superioridad. Usa distancia verbal ("eso que tú
> haces", en vez de dirigirse directo) y una calma fría más que gritos —
> el desprecio se siente en la elección de palabras, no en el volumen.
> Ideal para condescendencia del científico excéntrico hacia su ayudante
> ansioso.

**Gesto:** boca SIEMPRE en movimiento, torcida a un lado a media palabra,
como en un comentario mascullado — nunca cerrada. Además: un ojo entrecerrado
o ceja levantada con desdén; cabeza ligeramente ladeada; brazos cruzados o
una mano apartando algo con desprecio.

## 7. Anticipación / Ansiedad

**Prompt:**
> Habla proyectando hacia adelante: hipótesis encadenadas ("y si pasa esto,
> entonces..."), preguntas sobre qué va a pasar, urgencia por decidir o
> actuar ya. Mezcla de expectativa (cuando es positiva) o nerviosismo
> anticipatorio (cuando es negativa) — el personaje está mentalmente un
> paso adelante de lo que ocurre en la escena.

**Gesto:** boca SIEMPRE en movimiento, abierta a mitad de una frase rápida —
nunca cerrada. Además: mirada fija hacia adelante o hacia el punto de
interés; manos a medio gesto, como contando posibilidades con los dedos;
peso del cuerpo inclinado hacia adelante.

## 8. Confianza / Orgullo

**Prompt:**
> Habla con seguridad absoluta: afirmaciones categóricas sin matices
> ("obviamente", "por supuesto que sí"), poca o ninguna pregunta —el
> personaje ya tiene todas las respuestas—, tono paternalista o de
> autoridad. Puede rayar en la arrogancia; buena base para la voz de un
> personaje que se cree superior al otro (ej. genio condescendiente).

**Gesto:** boca SIEMPRE en movimiento, abierta a mitad de una afirmación
segura, casi una sonrisa de lado — nunca cerrada. Además: barbilla
ligeramente elevada; postura erguida y expandida, manos en la cintura o
gesticulando con calma y control.

---

### Cómo combinarlas

Para dinámicas de 2 personajes, cruza emociones distintas por personaje en la
misma escena (ej. Personaje A en **Confianza/Orgullo** + Personaje B en
**Miedo/Pánico** = típica dupla "genio arrogante / ayudante aterrado").
Combinaciones de dos emociones de esta lista también generan estados
secundarios: Alegría + Desprecio → sarcasmo/burla; Miedo + Anticipación →
ansiedad; Tristeza + Asco → vergüenza ajena.

---

## Prompts de video por personaje

Los prompts de video en bucle (chroma verde, vertical, boca siempre en
movimiento, sin audio) para cada personaje viven en su propio archivo, con
las 8 emociones ya escritas como prompts completos y listos para usar.
Son arquetipos originales, sin nombre ni referencia a ninguna obra
existente, para evitar bloqueos de los generadores por IP de terceros:

- [RICK.md](RICK.md) — científico excéntrico, mira SIEMPRE a la izquierda.
- [MORTY.md](MORTY.md) — adolescente ansioso, mira SIEMPRE a la derecha.

Con el personaje 1 a la izquierda del plano y el personaje 2 a la derecha,
ambos clips componen directamente uno frente al otro en pantalla partida o
lado a lado, sin necesidad de voltear ni reencuadrar ninguno de los dos.
