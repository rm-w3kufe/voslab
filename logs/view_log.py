#!/usr/bin/env python3
"""View the unified log with filtering and formatting.

Usage:
    python3 logs/view_log.py [options]

Options:
    --level LEVEL      Filter by level (decision, activation, trace, summary)
    --source SOURCE    Filter by source component name
    --last N           Show last N events (default: 20)
    --tree             Show socratic tree evaluations only
    --predicates       Show predicate registrations only
    --gates            Show gate evaluations only
    --stats            Show statistics by component
    --live             Live feed (follow new events)
    --verbose          Show full event details (trigger, reasoning, impact)
    --help             Show this help

Examples:
    python3 logs/view_log.py                         # últimos 20 eventos
    python3 logs/view_log.py --level decision        # solo decisiones
    python3 logs/view_log.py --source gate           # solo gates
    python3 logs/view_log.py --tree                  # árboles socráticos
    python3 logs/view_log.py --predicates            # registros de predicados
    python3 logs/view_log.py --last 50               # últimos 50 eventos
    python3 logs/view_log.py --stats                 # estadísticas
    python3 logs/view_log.py --live                  # live feed
    python3 logs/view_log.py --live --level decision # live feed de decisiones
    python3 logs/view_log.py --verbose               # detalles completos
"""
import json
import sys
import time
import os
from pathlib import Path
from collections import Counter, defaultdict


def parse_args(argv):
    """Parse command line arguments."""
    args = {
        'level': None,
        'source': None,
        'last_n': 20,
        'tree': False,
        'predicates': False,
        'gates': False,
        'stats': False,
        'live': False,
        'verbose': False,
        'help': False,
    }
    
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg == '--help' or arg == '-h':
            args['help'] = True
        elif arg == '--level' and i + 1 < len(argv):
            args['level'] = argv[i + 1]
            i += 1
        elif arg == '--source' and i + 1 < len(argv):
            args['source'] = argv[i + 1]
            i += 1
        elif arg == '--last' and i + 1 < len(argv):
            args['last_n'] = int(argv[i + 1])
            i += 1
        elif arg == '--tree':
            args['tree'] = True
        elif arg == '--predicates':
            args['predicates'] = True
        elif arg == '--gates':
            args['gates'] = True
        elif arg == '--stats':
            args['stats'] = True
        elif arg == '--live':
            args['live'] = True
        elif arg == '--verbose' or arg == '-v':
            args['verbose'] = True
        else:
            print(f"Unknown argument: {arg}", file=sys.stderr)
            sys.exit(1)
        i += 1
    
    return args


def load_events(log_path, max_tail=2000):
    """Load events from JSONL log file (tail-bounded).

    RAM-LIFECYCLE: the live log rotates at ~5M and history is append-only,
    so loading the whole file into heap grows without bound (20k+ lines).
    We read at most max_tail recent lines — enough for --last N and for
    filtered views of recent activity. Use --stats (streaming, no list)
    for full-history counts.
    """
    events = []
    with open(log_path, 'rb') as f:
        f.seek(0, 2)
        size = f.tell()
        # Walk back in chunks until we hold max_tail lines (or BOF)
        chunk = 64 * 1024
        buf = b''
        pos = size
        lines: list = []
        while pos > 0 and len(lines) <= max_tail:
            step = min(chunk, pos)
            pos -= step
            f.seek(pos)
            buf = f.read(step) + buf
            lines = buf.split(b'\n')
        for line in lines[-max_tail:]:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line.decode('utf-8', errors='replace')))
            except:
                pass
    return events


def filter_events(events, args):
    """Apply filters to events."""
    filtered = events
    
    # Filter by level (handle both old and new format)
    if args['level']:
        filtered = [e for e in filtered if 
                   e.get('level') == args['level'] or 
                   (e.get('instrument') == args['level']) or
                   (e.get('hook') == args['level'])]
    
    # Filter by source (handle both old and new format)
    if args['source']:
        filtered = [e for e in filtered if 
                   args['source'] in (e.get('source') or '') or
                   args['source'] in (e.get('instrument') or '')]
    
    # Filter by tree evaluations
    if args['tree']:
        filtered = [e for e in filtered if 
                   e.get('event_type') == 'socratic.evaluate' or 
                   (e.get('level') == 'decision' and 'tree' in str(e.get('context', {}))) or
                   (e.get('hook') == 'evaluate' and 'tree' in str(e.get('action', '')))]
    
    # Filter by predicate registrations
    if args['predicates']:
        filtered = [e for e in filtered if 
                   'predicate' in str(e.get('action', '')).lower() or
                   'register' in str(e.get('action', '')).lower()]
    
    # Filter by gate evaluations
    if args['gates']:
        filtered = [e for e in filtered if 
                   e.get('event_type') == 'gate.evaluate' or
                   e.get('hook') == 'gate']
    
    return filtered


def format_event(e, verbose=False):
    """Format a single event for display."""
    ts = e.get('ts', '?')[:19]
    
    # New format (with level)
    if 'level' in e:
        level = e.get('level', '?')
        source = e.get('source', '?')
        result = e.get('result', '?')
        event_type = e.get('event_type', '')
        action = e.get('action', '')
        detail = e.get('detail', '')
        
        # Icons based on level and result
        if level == 'decision':
            icon = '🧠'
        elif level == 'activation':
            if result == 'ok':
                icon = '✅'
            elif result == 'warn':
                icon = '⚠️'
            elif result == 'error':
                icon = '❌'
            else:
                icon = '⚡'
        elif level == 'summary':
            icon = '📊'
        else:
            icon = '📍'
        
        # For tree evaluations, show more detail
        if event_type == 'socratic.evaluate':
            context = e.get('context', {})
            tree = context.get('tree', '')[:50]
            certified = context.get('certified', False)
            reasoning = e.get('reasoning', {})
            why = reasoning.get('why', '')[:60] if reasoning else ''
            
            if verbose and why:
                return f'{icon} {ts}  {level:10s}  {source:25s}  truth={result:8s}  certified={certified}\n{"":>45s}  WHY: {why}'
            return f'{icon} {ts}  {level:10s}  {source:25s}  truth={result:8s}  certified={certified}  tree={tree}'
        
        # For RSI evaluations, show more detail
        if event_type == 'rsi_evaluate':
            if verbose:
                lines = [f'{icon} {ts}  {level:10s}  {source:25s}  {result:5s}  {event_type}']
                if action:
                    lines.append(f'{"":>45s}  ACTION: {action[:80]}')
                if detail:
                    lines.append(f'{"":>45s}  DETAIL: {detail[:100]}')
                return '\n'.join(lines)
            action_short = action[:50] if action else ''
            return f'{icon} {ts}  {source:25s}  {result:8s}  {event_type:25s}  {action_short}'
        
        # Verbose mode: show full details
        if verbose:
            lines = [f'{icon} {ts}  {level:10s}  {source:25s}  {result:5s}  {event_type}']
            
            # Action
            if action:
                lines.append(f'{"":>45s}  ACTION: {action[:100]}')
            
            # Trigger
            trigger = e.get('trigger', {})
            if trigger:
                lines.append(f'{"":>45s}  TRIGGER: {trigger.get("event", "?")} from {trigger.get("source", "?")}')
            
            # Reasoning
            reasoning = e.get('reasoning', {})
            if reasoning:
                lines.append(f'{"":>45s}  WHY: {reasoning.get("why", "?")}')
                if reasoning.get('prerequisites'):
                    lines.append(f'{"":>45s}  PREREQS: {", ".join(reasoning["prerequisites"][:3])}')
                if reasoning.get('chosen'):
                    lines.append(f'{"":>45s}  CHOSEN: {reasoning["chosen"][:80]}')
            
            # Impact
            impact = e.get('impact', {})
            if impact:
                lines.append(f'{"":>45s}  IMPACT: {impact.get("scope", "?")} (reversible={impact.get("reversible", "?")})')
                if impact.get('side_effects'):
                    lines.append(f'{"":>45s}  EFFECTS: {", ".join(impact["side_effects"][:2])}')
            
            # Metrics
            metrics = e.get('metrics', {})
            if metrics:
                parts = []
                if metrics.get('duration_ms') is not None:
                    parts.append(f'{metrics["duration_ms"]}ms')
                if metrics.get('success_rate') is not None:
                    parts.append(f'{metrics["success_rate"]*100:.0f}%')
                if parts:
                    lines.append(f'{"":>45s}  METRICS: {", ".join(parts)}')
            
            # Detail
            if detail:
                lines.append(f'{"":>45s}  DETAIL: {detail[:100]}')
            
            return '\n'.join(lines)
        
        # Normal mode: show action inline
        action_short = action[:50] if action else ''
        return f'{icon} {ts}  {source:25s}  {result:8s}  {event_type:25s}  {action_short}'
    
    # Old format
    else:
        instrument = e.get('instrument', '?')
        hook = e.get('hook', '?')
        result = e.get('result', '?')
        action = e.get('action', '')
        detail = e.get('detail', '')
        
        icon = '✅' if result == 'ok' else '⚠️' if result == 'warn' else '❌' if result == 'error' else '📍'
        
        # Inline: show action for non-ok results, truncate for ok
        if result == 'ok':
            action_short = action[:50] if action else ''
            return f'{icon} {ts}  {instrument:25s}  {result:8s}  {hook:25s}  {action_short}'
        else:
            # For errors/warnings: show full action inline
            return f'{icon} {ts}  {instrument:25s}  {result:8s}  {hook:25s}  {action}'


def show_stats(log_path):
    """Show statistics by component and level (streaming, bounded memory)."""
    print("\n══ ESTADÍSTICAS ══\n")
    level_counts = Counter()
    source_counts = Counter()
    type_counts = Counter()
    with_reasoning = with_trigger = with_impact = total = 0
    with open(log_path, 'rb') as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                e = json.loads(raw.decode('utf-8', errors='replace'))
            except:
                continue
            total += 1
            level_counts[e.get('level', 'unknown')] += 1
            source_counts[e.get('source') or e.get('instrument', 'unknown')] += 1
            type_counts[e.get('event_type', 'unknown')] += 1
            if e.get('reasoning'):
                with_reasoning += 1
            if e.get('trigger'):
                with_trigger += 1
            if e.get('impact'):
                with_impact += 1

    print("Por nivel:")
    for level, count in level_counts.most_common():
        print(f"  {count:4d}  {level}")

    print("\nPor componente:")
    for source, count in source_counts.most_common(10):
        print(f"  {count:4d}  {source}")

    print("\nPor tipo de evento:")
    for event_type, count in type_counts.most_common():
        print(f"  {count:4d}  {event_type}")

    print(f"\nCobertura de trazabilidad:")
    print(f"  {with_reasoning:4d}  con reasoning ({with_reasoning*100/max(total,1):.0f}%)")
    print(f"  {with_trigger:4d}  con trigger ({with_trigger*100/max(total,1):.0f}%)")
    print(f"  {with_impact:4d}  con impact ({with_impact*100/max(total,1):.0f}%)")


def live_feed(log_path, args):
    """Follow new events in real-time (like tail -f)."""
    print("══ LIVE FEED ══ (Ctrl+C para salir)\n")
    
    # Get initial file size
    try:
        with open(log_path, 'rb') as f:
            f.seek(0, 2)  # Seek to end
            file_size = f.tell()
    except FileNotFoundError:
        print(f"Error: Log file not found at {log_path}", file=sys.stderr)
        sys.exit(1)
    
    try:
        while True:
            # Check for new content
            try:
                with open(log_path, 'rb') as f:
                    f.seek(0, 2)  # Seek to end
                    new_size = f.tell()
                    
                    if new_size < file_size:
                        # Log rotated under us: resync to the new (small) file
                        file_size = new_size
                    elif new_size > file_size:
                        # Read new content
                        f.seek(file_size)
                        new_content = f.read().decode('utf-8', errors='replace')
                        file_size = new_size
                        
                        # Process new lines
                        for line in new_content.strip().split('\n'):
                            if line.strip():
                                try:
                                    e = json.loads(line.strip())
                                    filtered = filter_events([e], args)
                                    if filtered:
                                        print(format_event(e, verbose=args['verbose']))
                                except json.JSONDecodeError:
                                    pass
            except FileNotFoundError:
                pass
            
            time.sleep(0.5)  # Check every 500ms
            
    except KeyboardInterrupt:
        print("\n\n══ LIVE FEED DETENIDO ══")


def main():
    # Resolve log path relative to this script's location
    script_dir = Path(__file__).parent
    log_path = script_dir / "agent_plugin.jsonl"
    
    if not log_path.exists():
        print(f"Error: Log file not found at {log_path}", file=sys.stderr)
        sys.exit(1)
    
    args = parse_args(sys.argv)
    
    if args['help']:
        print(__doc__)
        sys.exit(0)
    
    # Live feed mode
    if args['live']:
        live_feed(log_path, args)
        return
    
    # Normal mode
    events = load_events(log_path)
    filtered = filter_events(events, args)
    
    # Show last N
    filtered = filtered[-args['last_n']:]
    
    # Print
    for e in filtered:
        print(format_event(e, verbose=args['verbose']))
        print()  # Blank line between events
    
    # Stats
    print(f'\n--- {len(filtered)} eventos mostrados ---')
    
    if args['stats']:
        show_stats(log_path)


if __name__ == '__main__':
    main()
