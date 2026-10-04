# Brief para Qwen: D-OLLAMA-EXPOSURE

**Decisión:** ¿Mantener Ollama escuchando solo en `127.0.0.1` dentro de LXC
101, o exponerlo en el bridge VLAN20 para consumo desde otros LXCs?

**Status:** **Decisión tomada en favor de exposición VLAN20.** Este brief
busca peer review arquitectónico antes de ejecutar el cambio.

---

## 1. Contexto

VSF (Viable System Framework) corre el "núcleo colapsado" en LXC 101 de
n02 (Proxmox): `vsf-nucleus` (Rust, S4 cognitive layer) + Ollama
(`qwen2.5-coder:7b`) comparten LXC. Comunicación entre ambos: loopback
TCP `127.0.0.1:11434`. Ningún otro LXC puede invocar al LLM.

Hoy hay 5 LXCs activos:
- 101 (nucleus + ollama)
- 104 (bbs-bridge + g6-sink + s5-algedonic + s5_console)
- 106 (nats-server + bbs-api)
- 107 (vsf-s3-star)
- (105 sin servicio, reservado para BBH-prod)

VLAN topology: VLAN10 (mgmt), VLAN20 (inter-LXC bridge,
`10.10.20.0/24`), VLAN30 (egress), VLAN40 (reserved).

NATS broker en `10.10.20.20:4222` (LXC 106) es el canal estándar
inter-LXC.

## 2. La pregunta

Cuando llegue un consumidor nuevo del LLM (caso de uso anticipado:
BBH-analyzer en LXC 105 cuando se reactive, o el opsroom panel
analítico, o un S5 console con RAG sobre la chain), debe poder
invocar Ollama. Dos caminos:

### Opción A: Mantener loopback (status quo)

- Ollama sigue en `127.0.0.1:11434` dentro de LXC 101.
- Consumidor nuevo en LXC 105 (por ejemplo) NO puede invocar
  directamente.
- Workarounds: (a) levantar otro Ollama en su propio LXC; (b)
  proxy a través del nucleus (nucleus expone su propio endpoint que
  internamente llama a Ollama); (c) tunneling SSH dentro del cluster.

### Opción B: Exponer en VLAN20 + firewall (decisión actual)

- Ollama listen `0.0.0.0:11434` dentro de LXC 101 (efectivamente
  alcanzable desde `10.10.20.10:11434` en VLAN20).
- nftables/iptables a nivel LXC bridge: solo IPs whitelisted en
  VLAN20 pueden conectar. Default-deny.
- Whitelist inicial: solo LXC 105 (BBH-prod, cuando active) y la
  IP del opsroom proxy (cuando exista).
- Cualquier consumidor nuevo se agrega mediante regla explícita +
  registro en `state.db` (componente con `llm_consumer: true`).

## 3. Razonamiento del operador para B

Citando al operador (decisión, 2026-05-31):

> *"Vamos a priorizar la escalabilidad y acoplamiento de aplicaciones,
> especialmente las que requieran gestión de la complejidad. Podemos
> controlar el flujo fuera de la VLAN con firewall y reglas de
> implementación o cumplimiento de condiciones para el acoplamiento.
> Lo principal es facilitar el acoplamiento sin necesidad de
> refactorizar el sistema. Principio de escalabilidad."*

Mi (Claude) lectura cibernética: el principio expresado se alinea con
**Ashby aplicada a interfaces** — la variedad de consumidores futuros
excede la variedad anticipable hoy; encapsular contra esa
incertidumbre cuesta más que abrir + controlar el flujo en la capa
de red. El "núcleo primero" no contradice esto — el núcleo es el
modelo cognitivo (S4 + covenant + chain). Ollama es infraestructura
de cómputo. Encapsular infra para futuros consumidores hipotéticos
viola YAGNI sin defenderse contra ningún caso conocido.

## 4. Lo que Qwen debería evaluar

1. **¿La filosofía cibernética encaja?** ¿Hay alguna lectura de Beer /
   Espejo que favorezca encapsulamiento sobre apertura controlada en
   este caso específico?
2. **¿La superficie de ataque es manejable?** Asumiendo nftables
   default-deny + whitelist explícita por IP, ¿qué vectores quedan
   abiertos? (Recordar: VLAN20 es interna; no hay rutas desde
   Internet.)
3. **¿Costo de carga (tokens)?** Ollama no autentica. Un LXC
   comprometido en VLAN20 podría drenar tokens libremente. Mitigación
   actual = limitar quién puede entrar a VLAN20 (firewall + Proxmox
   ACLs), no auth a nivel Ollama. ¿Suficiente?
4. **¿Esta decisión cierra opciones futuras?** ¿Habría que revertirla
   si introducimos autenticación a nivel Ollama (e.g., LiteLLM proxy)?
5. **Patrón evolutivo:** ¿Cuándo, en términos del crecimiento del
   sistema, esta arquitectura empieza a oler mal? (e.g., 3+ LXCs
   consumidores, 5+ consumidores...).
6. **Operacionalmente:** ¿el cambio sugerido (Ollama listen
   `0.0.0.0` + firewall) introduce algún punto único de falla nuevo,
   o reduce el actual?

## 5. Implementación planeada (si B confirma)

```bash
# Inside LXC 101:
sed -i 's|^Environment=OLLAMA_HOST=.*|Environment=OLLAMA_HOST=0.0.0.0:11434|' \
    /etc/systemd/system/ollama.service
systemctl daemon-reload && systemctl restart ollama

# nftables on n02 host (LXC bridge level):
nft add table inet vsf_llm
nft add chain inet vsf_llm input { type filter hook prerouting priority -150 \; policy drop \; }
nft add rule inet vsf_llm input ip saddr 10.10.20.10 tcp dport 11434 accept       # LXC 101 self
nft add rule inet vsf_llm input ip saddr 10.10.20.15 tcp dport 11434 accept       # LXC 105 BBH (planned)
# add more as components register llm_consumer:true in state.db
```

Plus: añadir columna `llm_consumer: BOOLEAN` a `state.db.components`,
y una validación que ejecute `vsf-state-populate` para verificar que
el firewall coincide con la lista declarada.

## 6. Lo que pedimos a Qwen

Una respuesta breve (1-2 párrafos) con:
- Endorso / objeción a la decisión B
- Cualquier punto de §4 que merezca atención que no esté ya cubierto
- Sugerencia operacional si la hay

Si Qwen tiene reservas fuertes, identificar el switch concreto que
las resolvería (e.g., "OK si LiteLLM proxy con API keys", "OK si la
whitelist se valida automáticamente al spawn de cada LXC", etc).

---

**Para enviar a:** chat.qwen.ai (consenso architectural rounds 1-4
ya establecidos sobre `telemetry_canonical`; este brief continúa la
relación).

**Generado por:** Claude, 2026-05-31, cycle-3 post-audit.
