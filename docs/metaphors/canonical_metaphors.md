# Metáforas Canónicas

*Traducir un sistema viable a personas que no leen cibernética — sin mentirles.*

---

## Por qué existe este repositorio

Un sistema viable es abstracto. Las cinco funciones, la variedad requerida, la
proyección anticipatoria: son ideas precisas, pero no entran por la puerta de nadie
que no haya leído a Beer. La metáfora es el puente.

Pero una metáfora es un préstamo contra la comprensión. Compra claridad escondiendo
detalle, y el interés se paga exactamente donde la analogía se rompe. El campesino que
riega antes de la sequía explica la anticipación de maravilla — hasta que alguien
pregunta "¿y puede regar contra la sequía del próximo año?" y descubre que no, que solo
ve un día adelante. Si esa pregunta no estaba respondida de antemano, la metáfora no
enseñó: engañó.

De ahí la **regla de la casa**, la única innegociable de este repositorio:

> **Ninguna metáfora entra sin declarar dónde se rompe.**
> Una metáfora sin punto de quiebre no es pedagogía: es propaganda.

Es la misma disciplina que gobierna todo lo demás acá. El crédito que cerró este ciclo
(+0.9 de autonomía en S4) se ganó cortando en ambos sentidos: se negó cuando no
correspondía, se retractó cuando falló una prueba, y se acreditó solo cuando la evidencia
lo sostuvo. Una metáfora honesta hace lo mismo: dice lo útil y, en la misma respiración,
dice exactamente hasta dónde es cierto.

---

## Cómo agregar una metáfora

Cada entrada tiene cuatro campos. Los cuatro son obligatorios; el tercero es el que
distingue este repositorio de un folleto.

- **Traduce:** *un* concepto, no diez. Si tu metáfora explica cinco cosas, probablemente
  no explica bien ninguna.
- **La historia:** concreta, cotidiana, sin jerga. Si necesitas una nota al pie, todavía
  no es una metáfora.
- **Dónde se rompe:** el punto exacto donde deja de ser cierta. Obligatorio. Aquí se paga
  el préstamo.
- **En el sistema:** el mecanismo real que traduce, con puntero, para quien quiera bajar
  del cuento al fierro.

---

## Parte I — Qué *es* el sistema

### El taller y sus cinco oficios

**Traduce:** las cinco funciones de un sistema viable (S1–S5).

**La historia.** Imagina un taller que sobrevive por décadas. Hay cinco oficios, y
ninguno sobra. **Las manos** (S1) hacen el trabajo: cortan, sueldan, arman. Los **reflejos
compartidos** (S2) evitan que dos manos alcancen la misma herramienta al mismo tiempo — no
mandan, solo impiden el choque. El **jefe de piso** (S3) reparte lo que hay: quién usa qué,
cuánto, cuándo. El **inspector sorpresa** (S3\*) aparece sin avisar y mira lo que los
informes no muestran. El **vigía en el techo** (S4) no mira el taller: mira el horizonte, la
calle, el clima, lo que viene. Y la **constitución** (S5) fija los límites que nadie —
tampoco el jefe— puede saltarse. Un taller vivo tiene los cinco. Quítale el vigía y sobrevive
hasta la primera sorpresa; quítale la constitución y el más fuerte se lo come.

**Dónde se rompe.** En un taller de verdad los oficios se mezclan: la misma persona a veces
corta y a veces reparte. En un cuerpo, aún peor: no hay un "jefe de piso" que puedas señalar.
La separación es un lente para *diagnosticar*, no un plano de cómo se ve por dentro. Y hay una
diferencia que el taller no captura: aquí cada mano puede ser, ella misma, un taller completo
con sus propios cinco oficios (ver *las muñecas rusas*).

**En el sistema:** S1–S5 en `viability.yaml`; `docs/concepts.md`; patrón Cybersyn.

---

## Parte II — Qué *hace*

### El campesino que riega antes de la sequía

**Traduce:** la anticipación — la proyección de S4 que actúa *antes* de la excursión.

**La historia.** Dos campesinos, el mismo campo, la misma agua. El primero riega cuando la
planta ya está mustia: reacciona al daño. El segundo lee el cielo y la tierra, y riega el día
*antes* de que llegue el calor. No usó más agua — usó la misma, movida un día antes, guiada por
una lectura del horizonte. Su planta nunca se marchita. Eso es toda la anticipación: no más
recursos, los mismos recursos movidos a tiempo, porque alguien miró hacia adelante.

**Dónde se rompe.** La lectura del cielo solo sirve tan lejos como el clima sea legible. Leído
demasiado lejos, el campesino ya no está anticipando: está adivinando el promedio de la estación
—que es nuestro límite exacto—. Nuestro "cielo" es legible como un día; más allá, la proyección
converge a la tasa base (ver *la tabla actuarial*). Y una honestidad más: por ahora nuestro
campesino riega en un ensayo — la reasignación está validada pero es *simulada*, no actuada
todavía sobre tierra real.

**En el sistema:** proyección Markov de S4 → reasignación anticipatoria; EXP-S4-01
(las cuatro hipótesis pasan en una config; efecto ~14%, adelanto 1 día);
`docs/spec_revision/system/s4-intelligence/theory-ap-01/anticipatory_prevention.vsm`.

### El precio de seguir siendo uno mismo

**Traduce:** la viabilidad epistémica — el costo continuo de mantener la coherencia.

**La historia.** Un cuerpo en reposo parece no hacer nada. Pero está pagando, cada segundo,
por mantener su temperatura y su química dentro de la banda estrecha donde la vida es posible.
Seguir siendo uno mismo no es gratis: es una cuenta que se paga sin parar contra la corriente
que empuja hacia la disolución. Un sistema que deja de pagar no se queda quieto — se deshace.
Existir ya cuesta; *conocer* cuesta aparte.

**Dónde se rompe.** Los "dos precios" —el de existir y el de conocer— son más nítidos en la
metáfora que en la matemática, donde se enredan. Y hay una asimetría que el cuerpo no muestra:
la banda de un cuerpo la fija la biología, y no se equivoca; la nuestra la fija una política
(ver *el termostato*), y sí puede estar mal. Nuestra banda es una decisión, no una ley de la
naturaleza.

**En el sistema:** paper *epistemic_viability*; la región viable Ω; `stasis_cos`.

### La mano que se retira antes de que el cerebro decida

**Traduce:** la señal algedónica — el canal de dolor/placer que evita la capa lenta.

**La historia.** Tocas una olla caliente y tu mano se retira *antes* de que hayas pensado la
palabra "caliente". La señal no espera a la deliberación: tiene un cable propio, rápido, directo
a la acción. Un sistema viable necesita ese cable — un canal de alarma que se salta la capa
pensante cuando algo es urgente, porque pensar toma tiempo y a veces el tiempo es justo lo que
no hay.

**Dónde se rompe.** Un reflejo es tonto por diseño — puede retirar la mano de un calor que
confundió con fuego. Por eso el reflejo nunca puede ser el único juez: la capa lenta revisa
después. En nuestro sistema el camino reflejo es *determinista* y tiene prohibido usar el modelo
de lenguaje (regla R10), precisamente porque un reflejo "inteligente" es un reflejo lento, y un
reflejo lento no es un reflejo.

**En el sistema:** canal algedónico; reglas R10/R10.1; `vsf-s5-algedonic`.

### El arquero y la variedad requerida

**Traduce:** la Ley de Ashby — para regular algo necesitas al menos tanta variedad como te lanza.

**La historia.** Un arquero solo puede atajar tantos *tipos* de tiro como tipos de atajada tenga.
Enfréntalo a un delantero con más trucos que atajadas tiene el arquero, y será batido — no por
mala suerte, por aritmética. Para controlar algo necesitas al menos tanta variedad como ese algo
te arroja. No es un eslogan: es una ley, tan dura como la de la palanca.

**Dónde se rompe.** La metáfora sugiere que la única salida es *crecer* tu variedad hasta igualar
la del mundo. Falso, y peligroso: a veces la jugada honesta es *reducir* la variedad del mundo —
achicar el arco, poner un filtro, coordinar para que no lleguen todos los tiros a la vez— en lugar
de fingir que puedes atajarlo todo. La ley dice que necesitas la variedad; no dice que debas
conseguirla creciendo. Eso es lo que hacen S2 y los filtros.

**En el sistema:** Cyberfilter/S3, coordinación S2; Ashby como fundamento de la variedad.

---

## Parte III — Qué *no* hace

*(La parte más importante para la confianza. Un sistema que solo publicita lo que hace es un
vendedor; uno que publicita con igual cuidado lo que no hace es un socio.)*

### La tabla actuarial, no el pronóstico del tiempo

**Traduce:** el alcance real del modelo climático — da tasas base, no predice eventos.

**La historia.** La tabla de un actuario de seguros te dice que una persona de 60 años tiene,
digamos, 2% de probabilidad de tal cosa este año. Es verdad, es útil, y no sabe *nada* de ti: ni
tu nombre, ni tu martes que viene. Da tasas históricas, no predicciones de eventos. Nuestro modelo
climático es exactamente eso: te dice a qué ritmo histórico una zona se desvía hacia el estrés. No
sabe que viene un río atmosférico la próxima semana. Pídele que pronostique la tormenta y te
entregará el promedio del siglo, tan tranquilo.

**Dónde se rompe.** Esta metáfora *es* el punto de quiebre del campesino: aquí es donde "leer el
horizonte" se acaba. Y se rompe aún más si la empujas: pasado un día, nuestra tabla se olvida de
dónde partiste y solo repite la tasa base (~20% desde cualquier estado). Es una tabla actuarial con
un día de memoria. Sirve para entender el *régimen* de una zona, jamás para saber si lloverá el
jueves — para eso, un modelo meteorológico, no éste.

**En el sistema:** cadena de Markov de 5 bins por percentil; climatología ERA5 1991–2020; bloques
de aviso en `scripts/reportes/reporte_clima_*.py`.

### El mapa no es el territorio

**Traduce:** la regla "modelo ≡ realidad" — y por qué es una disciplina, no una omnisciencia.

**La historia.** Un mapa es útil *precisamente* porque deja cosas afuera. Pero un mapa que se cree
el territorio es peligroso: manejarás directo al lago que simplificó. Nuestra regla "modelo ≡
realidad" es una disciplina para mantener el mapa honesto — cada servicio que el mapa declara tiene
que existir de verdad, y un censo lo verifica— no una afirmación de que el mapa *es* el mundo.

**Dónde se rompe.** Un mapa perfectamente reconciliado sigue siendo un mapa: puede ser verdadero
sobre lo que muestra y mudo sobre lo que nunca relevó. La reconciliación te compra "sin mentiras",
no "sin huecos". Lo no instrumentado no aparece — y no aparecer no es lo mismo que no existir.

**En el sistema:** `model≡reality`; `topology_reconcile`; el censo anti-huérfanos (S3\*).

---

## Parte IV — Cómo se gobierna

### El corazón — el quinto que une

**Traduce:** S5 como *identidad* — no lo que el sistema hace, sino lo que *es*; el quinto oficio que
vuelve *uno* a los otros cuatro.

**La historia.** En una vieja serie de dibujos animados, cada continente tenía un guardián y un
elemento: tierra, fuego, viento, agua. Y un quinto — el **Corazón** —, el que le tocó a Sudamérica.
Parecía el más débil, el "blando" al lado del fuego y la tierra. Pero era el que unía a los otros
cuatro: sin él, eran cuatro fuerzas sueltas; con él, se convocaban en un solo ser. S5 es ese quinto.
No es la fuerza que corta ni la mano que reparte: es lo que hace que las manos, los reflejos, el jefe
y el vigía sean *un* sistema y no cuatro que comparten dirección. Un taller con los primeros cuatro
oficios y sin el quinto es un cuerpo competente sin un sí-mismo: sabe hacer, pero no sabe *para qué*.
El corazón no es lo que más empuja — es lo que le da a todo lo demás una razón para sostenerse.

**Dónde se rompe.** El corazón engaña por dos lados. Primero: el corazón *de verdad* es una bomba,
músculo que hace circular. Esa bomba, en nuestro sistema, es el *jefe de piso* (S3), el que reparte y
hace circular los recursos — no S5. No confundas el corazón-máquina con el corazón-identidad. Segundo,
y más grave: el corazón se sentimentaliza —"sigue a tu corazón", el impulso, lo blando—. S5 es lo
*contrario*: es justamente lo que **no** cede al impulso del momento, el límite inmovible que ni el
más fuerte puede saltarse (ver *el termostato* y *la regla que ata al que hace las reglas*). Aquí el
corazón es duro: es el covenant, no el capricho. Y un último matiz: aquel Corazón no actuaba solo —
convocaba al todo *con* los otros cuatro. Una identidad sin operaciones es un eslogan, no un sistema;
S5 sin S1–S4 es un alma sin cuerpo. El quinto no es una corona sobre los demás: es el cierre que los
vuelve uno.

**En el sistema:** política S5; `covenant.vsm`; A0 (primacía ética); el CA S5 offline. Y una raíz que
la metáfora lleva consigo: el guardián del Corazón era sudamericano — la capa de identidad de este
trabajo, heredera de una cibernética que Chile ya tuvo una vez (Cybersyn, 1971).

### El termostato que nadie puede saltarse

**Traduce:** S5, la política — no hace el trabajo, fija la banda que el trabajo debe respetar.

**La historia.** Un termostato no calienta la pieza. Decide la *banda* en la que la pieza debe
quedarse, y nada dentro de la pieza tiene voto. S5 es el termostato del sistema: no ejecuta, fija
los límites que la ejecución no puede cruzar. Su poder no es la acción — es la última palabra sobre
los bordes.

**Dónde se rompe.** Un termostato mal puesto es una tiranía silenciosa: la pieza obedece un número
equivocado sin quejarse. Por eso quien fija la banda tiene que estar, a su vez, atado (ver *la regla
que ata al que hace las reglas*). Una banda que nadie puede saltarse solo es segura si cambiarla es
difícil y visible.

**En el sistema:** política S5; región viable Ω; piso del covenant.

### La regla que ata también al que hace las reglas

**Traduce:** A5, el techo de autonomía y el covenant — el sistema no puede votarse más poder.

**La historia.** La constitución más fuerte es la que ata a su propio autor — donde ni el rey puede,
por decreto, eximirse a sí mismo. En nuestro sistema la regla más profunda es que las correcciones
grandes —cambiar la banda misma, el "doble lazo"— siempre requieren que un humano diga que sí. El
sistema no puede votarse más autonomía. Puede proponerla; no puede tomársela.

**Dónde se rompe.** Una regla vale solo lo que vale su cumplimiento: un covenant que el que ejecuta
puede editar en silencio es una sugerencia. El nuestro es determinista y auditado (S3\*)
precisamente para que atar no dependa de las buenas intenciones. Y un matiz que la metáfora del rey
esconde: este techo es una *elección*, no una ley natural. Lo pusimos bajo a propósito — porque un
techo que el sistema escogió puede, en principio, volver a escoger, y por eso el candado está
afuera (ver el CA offline).

**En el sistema:** techo de autonomía A5; D4 lazo simple/doble; el covenant; CA S5 offline.

### El inspector que llega sin avisar

**Traduce:** S3\* — el audit esporádico que ve lo que los informes de S3 no muestran.

**La historia.** El jefe de piso (S3) ve los informes que las unidades *eligen* mandar. El inspector
sorpresa (S3\*) entra sin avisar y mira lo que los informes no muestran — el cajón que nadie
mencionó. No porque las unidades mientan, sino porque todo canal de reporte tiene un punto ciego, y
la única cura para un punto ciego es una mirada desde el ángulo que ese canal no cubre.

**Dónde se rompe.** El inspector es esporádico por diseño. Vuélvelo constante y se convierte en otro
canal de reporte más, con su propio punto ciego — y de paso estrangula el trabajo que audita. Su
valor está en la sorpresa y en el ángulo distinto, no en la cobertura total. Un inspector que mira
todo, todo el tiempo, ya no es un inspector: es la burocracia que vino a evitar.

**En el sistema:** audit S3\*; reconciliación anti-huérfanos; `vsf-s3-star`.

---

## Parte V — La forma del todo

### Las muñecas rusas

**Traduce:** la recursión — cualquier unidad que hace trabajo puede ser, ella misma, un sistema completo.

**La historia.** Abres una muñeca rusa y adentro hay una muñeca *entera* — no un pedazo de una,
una completa. La abres y hay otra. Nuestro sistema está construido así: cualquier unidad que hace
trabajo (un S1) puede ser, por dentro, un sistema completo con sus propios cinco oficios. Son
muñecas hasta el fondo, y cada muñeca está entera.

**Dónde se rompe.** Las muñecas de verdad son idénticas y se acaban. Las nuestras difieren en cada
nivel y tienen que *ganarse* su completitud: una unidad cuenta como recursiva solo si pasa una
certificación, no por declararlo. Y el anidamiento toca fondo — en algún piso hay una mano real
haciendo trabajo real, no otra muñeca. La recursión es una estructura, no una excusa para nunca
llegar al suelo.

**En el sistema:** `recursive: true` + `vsf_ref`; DSN-EVC-01 (certificador embebido);
`docs/recursive_vsm_theory.md`.

---

## Coda

La disciplina de este repositorio es la del sistema entero, en miniatura: decir lo útil y, en la
misma respiración, decir exactamente dónde deja de ser cierto. El +0.9 que cerró este ciclo se ganó
cortando en ambos sentidos — negado cuando no correspondía, acreditado cuando la evidencia lo
sostuvo. Cada metáfora de acá se sostiene igual: no por lo que ilumina, sino por lo honesta que es
respecto de su propia sombra.

Una metáfora que no conoce su sombra no es un puente. Es una trampa con vista bonita.
