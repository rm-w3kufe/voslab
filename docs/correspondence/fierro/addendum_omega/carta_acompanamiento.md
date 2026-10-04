# Carta de acompañamiento — addendum a Prof. Fierro

> Base para que rmw3 adapte a su tono. Español (la carta es humana; el addendum,
> matemática). Marcadores [así] = personalizar. El párrafo §opcional puede
> incluirse o no según cuánto quieras extenderte. Notas de decisión al final.

---

Estimado profesor [Fierro / don Raúl]:

Vuelvo a escribirle para retomar el intercambio que abrió su revisión de mayo.
Le adjunto un addendum matemático que responde, punto por punto, a las tres
observaciones que usted planteó sobre la región Ω y la dinámica estocástica.

Sus tres objeciones resultaron ser exactamente los lugares donde el argumento
original cedía, y agradezco la precisión con que las señaló. En resumen de lo
que encontrará en el adjunto:

- Sobre la **convexidad** (su primera observación): tenía usted razón, Ω no es
  convexa, y la apelación a Brouwer no estaba justificada. El argumento corregido
  ya no depende de la convexidad en ningún paso — la existencia descansa ahora en
  Krylov–Bogoliubov (basta la compacidad) y en el principio de Banach sobre el
  núcleo contractivo.

- Sobre la **contractividad**: distinguimos lo que se demuestra de lo que se mide.
  En el núcleo, la contracción está certificada por el exponente de Lyapunov
  negativo. Fuera de él fuimos deliberadamente honestos: la cota de Lipschitz
  global es mayor que uno, y así lo declaramos; el confinamiento fuera del núcleo
  lo sostenemos como propiedad dinámica, no como hipótesis.

- Sobre el **ruido**: reemplazamos la invariancia punto a punto por viabilidad
  estocástica en el sentido de Aubin, con la condición de deriva de
  Foster–Lyapunov, que es precisamente la de ergodicidad geométrica de
  Meyn–Tweedie.

Si me permite una nota de gratitud que excede lo formal: sus preguntas dejaron de
ser observaciones sobre *este* trabajo y se convirtieron en un criterio que hoy
aplicamos a cada dominio nuevo antes de afirmar viabilidad. Lo que usted planteó
como revisión terminó siendo método.

§opcional — [Si quieres mostrarle el alcance:] Hemos aplicado ese criterio a dos
dominios independientes del original —una red climática y un modelo económico— y
en el segundo estamos diseñando deliberadamente una región Ω *no* convexa (un
anillo, con un piso y un techo), donde su primera pregunta reaparece con toda su
fuerza. Cómo certificar viabilidad en una región anular es una cuestión abierta
sobre la que su intuición nos sería muy valiosa.

Lo que quisiera pedirle, cuando su tiempo lo permita, es la revisión matemática
de cuerpo completo del trabajo: la cadena de existencia reformulada, la lógica de
convergencia, y el tratamiento del conjunto recurrente. No le pido premura —le
pido rigor, que es lo que siempre he recibido de usted.

Quedo muy agradecido por el tiempo ya invertido, y a la espera de lo que tenga a
bien señalarme.

Con aprecio,
[rmw3 / nombre]

---

## Notas de decisión (para ti, no van en la carta)

1. **Tratamiento**: dejé "[Fierro / don Raúl]" y "usted" — ajusta según tu
   relación real. Si fue tu profesor, "don Raúl" + usted es lo natural en Chile.

2. **El párrafo §opcional (dominios clima/econ + anillo Raworth)**: enriquece y
   le tiende un anzuelo matemático interesante (el problema del anillo no convexo
   es genuinamente bonito y podría engancharlo). Pero alarga y desvía del
   addendum. Mi recomendación: **inclúyelo** — a un matemático clásico un problema
   abierto elegante lo invita más que cualquier otra cosa. Pero si prefieres una
   carta breve y sobria, quítalo sin que nada se rompa.

3. **La mención del L_f > 1** ("fuimos deliberadamente honestos"): la dejé porque
   adelanta que fuimos rigurosos con nosotros mismos — desarma al revisor. Pero si
   la sientes demasiado técnica para una carta, puedes cortarla; el detalle está
   en el addendum de todos modos.

4. **Qué pides**: la revisión Q4 completa. Si por ahora solo quieres enviarle el
   addendum y esperar su reacción antes de pedir más, corta el penúltimo párrafo.

5. **Registro**: la carta menciona los nombres (Krylov–Bogoliubov, Banach, Aubin)
   sin explicarlos — para él son familiares y le dan el mapa del adjunto. No hay
   una sola palabra de "sistema", "kernel" ni "computación": eso es deliberado,
   para que reciba esto como matemática, según tu propia observación.

6. **Pendiente antes de enviar** (recordatorio del README): decidir qué versión
   del paper adjuntas (v0.9 con las adiciones de esta semana). — La deuda
   OMEGA-MARGIN quedó **cerrada con datos** (2026-07-14): el addendum §2 ahora
   cita el margen de viabilidad medido directamente (mediana 0.097, 100% viable,
   15,435 muestras / 10.7h). Ya NO hace falta nota de disculpa — cerramos con
   medición, no con caveat.
