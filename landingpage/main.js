(function () {
  'use strict';

  const SCROLL_THRESHOLD = 50;
  const REVEAL_THRESHOLD = 0.15;
  const CHAR_DELAY_MS = 25;
  const LOOP_PAUSE_MS = 2500;
  const ANIMATION_END_BUFFER_MS = 500;
  const COPY_REVERT_MS = 1500;

  const TERMINAL_SCRIPT = [
    { text: '$ agentharness brainstorm', delay: 0, cls: 't-cmd' },
    { text: '> Describe your feature: landing page for AgentHarness', delay: 1200, cls: 't-input' },
    { text: '✓ Brief uploaded: feat-20260427-abc123', delay: 2400, cls: 't-success' },
    { text: '$ agentharness implement feat-20260427-abc123', delay: 3200, cls: 't-cmd' },
    { text: '[analyst]    running...', delay: 4000, cls: 't-agent' },
    { text: '[analyst]    ✓ spec.r1.md uploaded', delay: 5200, cls: 't-success' },
    { text: '[architect]  running...', delay: 5600, cls: 't-agent' },
    { text: '[architect]  ✓ arch-review.r1.md uploaded', delay: 6800, cls: 't-success' },
    { text: '[planner]    running...', delay: 7200, cls: 't-agent' },
    { text: '[planner]    ✓ 3 tasks dispatched', delay: 8400, cls: 't-success' },
    { text: '[developer]  task-1: implement hero section...', delay: 8800, cls: 't-agent' },
    { text: '[reviewer]   task-1: PASS', delay: 10400, cls: 't-pass' },
    { text: '[developer]  task-2: implement features grid...', delay: 10800, cls: 't-agent' },
    { text: '[reviewer]   task-2: PASS', delay: 12000, cls: 't-pass' },
    { text: '[developer]  task-3: implement animations...', delay: 12400, cls: 't-agent' },
    { text: '[reviewer]   task-3: PASS', delay: 13600, cls: 't-pass' },
    { text: '✓ Feature complete: feat-20260427-abc123', delay: 14200, cls: 't-success' },
  ];

  const PIPELINE_SCRIPT = [
    { text: '$ agentharness observe', delay: 0, cls: 't-cmd' },
    { text: 'Observer started. Polling all queues...', delay: 600, cls: 't-input' },
    { text: '[analyst]    ← feat-20260427-abc123 dequeued', delay: 1400, cls: 't-agent' },
    { text: '[analyst]    running claude-opus-4-5 (max_turns=15)...', delay: 2000, cls: 't-agent' },
    { text: '[analyst]    ✓ spec.r1.md  →  artifact store', delay: 3800, cls: 't-success' },
    { text: '[architect]  ← feat-20260427-abc123 dequeued', delay: 4400, cls: 't-agent' },
    { text: '[architect]  running claude-opus-4-5 (max_turns=15)...', delay: 5000, cls: 't-agent' },
    { text: '[architect]  ✓ arch-review.r1.md  →  artifact store', delay: 6600, cls: 't-success' },
    { text: '[planner]    ← feat-20260427-abc123 dequeued', delay: 7200, cls: 't-agent' },
    { text: '[planner]    ✓ 3 tasks dispatched  →  developer-queue', delay: 8800, cls: 't-success' },
    { text: '[developer]  ← task-1 dequeued (serial)', delay: 9400, cls: 't-agent' },
    { text: '[developer]  running claude-sonnet-4-6 (max_turns=30)...', delay: 10000, cls: 't-agent' },
    { text: '[developer]  ## Status: DONE', delay: 12000, cls: 't-success' },
    { text: '[reviewer]   ← task-1 dequeued', delay: 12600, cls: 't-agent' },
    { text: '[reviewer]   **Status:** PASS', delay: 14000, cls: 't-pass' },
    { text: '[developer]  ← task-2 dequeued  (next pending)', delay: 14600, cls: 't-agent' },
    { text: '[reviewer]   task-2: PASS', delay: 17200, cls: 't-pass' },
    { text: '[developer]  ← task-3 dequeued  (next pending)', delay: 17800, cls: 't-agent' },
    { text: '[reviewer]   task-3: PASS', delay: 20600, cls: 't-pass' },
    { text: '✓ feat-20260427-abc123  →  state: done', delay: 21200, cls: 't-success' },
  ];

  function initNavbarScroll() {
    const header = document.getElementById('navbar');
    if (!header) return;

    const onScroll = () => {
      const shouldBeScrolled = window.scrollY > SCROLL_THRESHOLD;
      header.classList.toggle('scrolled', shouldBeScrolled);
    };

    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }

  function initScrollReveal() {
    const targets = document.querySelectorAll('.reveal');
    if (!targets.length) return;

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          entry.target.classList.add('is-visible');
          observer.unobserve(entry.target);
        });
      },
      { threshold: REVEAL_THRESHOLD }
    );

    targets.forEach((el) => observer.observe(el));
  }

  function buildTerminalLine(text, cls) {
    const span = document.createElement('span');
    span.className = cls;
    span.setAttribute('aria-label', text);
    return span;
  }

  function typeCharacters(span, text, isActiveRef, onDone) {
    let index = 0;

    const tick = () => {
      if (!isActiveRef()) return;
      if (index >= text.length) {
        onDone();
        return;
      }
      span.textContent += text[index];
      index += 1;
      setTimeout(tick, CHAR_DELAY_MS);
    };

    tick();
  }

  function createTimeoutScheduler() {
    let pending = [];

    const schedule = (fn, delay) => {
      const id = setTimeout(fn, delay);
      pending = [...pending, id];
      return id;
    };

    const clear = () => {
      pending.forEach(clearTimeout);
      pending = [];
    };

    return { schedule, clear };
  }

  function createScriptRunner(container, script, isActiveRef) {
    const { schedule, clear } = createTimeoutScheduler();
    let running = false;

    const run = () => {
      if (running) return;
      running = true;
      container.innerHTML = '';
      const lastEntry = script[script.length - 1];
      const totalDuration = lastEntry.delay + lastEntry.text.length * CHAR_DELAY_MS + ANIMATION_END_BUFFER_MS;

      script.forEach(({ text, delay, cls }) => {
        schedule(() => {
          if (!isActiveRef()) return;
          const line = document.createElement('div');
          const span = buildTerminalLine('', cls);
          line.appendChild(span);
          container.appendChild(line);
          container.scrollTop = container.scrollHeight;
          typeCharacters(span, text, isActiveRef, () => {
            container.scrollTop = container.scrollHeight;
          });
        }, delay);
      });

      schedule(() => {
        running = false;
        if (isActiveRef()) schedule(run, LOOP_PAUSE_MS);
      }, totalDuration);
    };

    const stop = () => { running = false; clear(); };

    return { run, stop };
  }

  function runTerminalAnimation(containerId, script) {
    const container = document.getElementById(containerId);
    if (!container) return;

    let isActive = false;
    const isActiveRef = () => isActive;
    const runner = createScriptRunner(container, script, isActiveRef);

    const sectionId = containerId === 'terminal-hero' ? 'hero' : 'pipeline';
    const section = document.getElementById(sectionId);

    if (!section) {
      isActive = true;
      runner.run();
      return;
    }

    new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          isActive = true;
          runner.run();
        } else {
          isActive = false;
          runner.stop();
        }
      },
      { threshold: 0 }
    ).observe(section);
  }

  function initCopyButtons() {
    document.querySelectorAll('.copy-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const textToCopy = btn.getAttribute('data-copy');
        if (!textToCopy) return;

        const showCopied = () => {
          const label = btn.querySelector('.copy-label');
          if (label) label.textContent = 'Copied!';
          btn.classList.add('copied');
          setTimeout(() => {
            if (label) label.textContent = 'Copy';
            btn.classList.remove('copied');
          }, COPY_REVERT_MS);
        };

        const fallbackCopy = () => {
          const ta = document.createElement('textarea');
          ta.value = textToCopy;
          ta.style.cssText = 'position:fixed;opacity:0';
          document.body.appendChild(ta);
          ta.select();
          document.execCommand('copy');
          document.body.removeChild(ta);
          showCopied();
        };

        if (navigator.clipboard) {
          navigator.clipboard.writeText(textToCopy).then(showCopied).catch(fallbackCopy);
        } else {
          fallbackCopy();
        }
      });
    });
  }

  function initFooterYear() {
    const el = document.getElementById('footer-year');
    if (el) el.textContent = String(new Date().getFullYear());
  }

  function init() {
    initNavbarScroll();
    initScrollReveal();
    initCopyButtons();
    initFooterYear();
    runTerminalAnimation('terminal-hero', TERMINAL_SCRIPT);
    runTerminalAnimation('terminal-pipeline', PIPELINE_SCRIPT);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
