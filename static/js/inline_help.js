/**
 * inline_help.js — Inline hover tooltips for contextual help
 * Adds small ℹ help icons next to UI elements that show rich tooltips on hover.
 * 
 * Usage:
 *   InlineHelp.attach(selector, tooltipText, options)
 *   InlineHelp.attachMany(definitions)     // bulk attach
 *   InlineHelp.refreshAll()                // re-attach after DOM changes
 * 
 * Or via data attributes in HTML:
 *   <span data-inline-help="Erklärungstext hier">Label</span>
 */
(function() {
    'use strict';

    // ── Tooltip Definitions per Page ─────────────────────────────────
    // Key = page identifier (matched via URL), value = array of definitions
    const TOOLTIP_DEFS = {

        // ── Dashboard ────────────────────────────────────────────────
        dashboard: [
            {
                selector: '#kpiRow',
                text: 'Gesamtstatistiken über alle Batches: Wellen, Batches, Dokumente, Upload-Erfolge, Verlinkungen und Fehler.',
                position: 'bottom'
            },
            {
                selector: '.phase-progress',
                text: '3 Phasen-Balken: Vorbereitung → Upload → Verlinkung.\n■ Grün = fertig, ■ Blau (pulsierend) = aktiv, ■ Grau = ausstehend, ■ Rot = Fehler',
                position: 'top',
                attachTo: 'each'
            }
        ],

        // ── Preview ──────────────────────────────────────────────────
        preview: [
            {
                selector: '#btnRefreshData',
                text: 'WICHTIG! Lädt LOIO-IDs, Dateigrößen, Dateinamen und wendet Migrationsregeln an. Muss vor dem Upload ausgeführt werden.',
                position: 'bottom'
            },
            {
                selector: '#btnStartMigration',
                text: 'Startet den Upload: Für jeden Datensatz wird ein Container im Zielsystem erstellt und die Datei(en) übertragen.',
                position: 'bottom'
            },
            {
                selector: '#btnResetFailed',
                text: 'Setzt fehlgeschlagene Datensätze zurück, damit sie erneut versucht werden können.',
                position: 'bottom'
            }
        ],

        // ── Prepare ──────────────────────────────────────────────────
        prepare: [
            {
                selector: '#btnLoadDmsObjects',
                text: 'Fragt 11 DMS-Objekttypen (EQUI, IFLOT, MPLA, etc.) aus der DIL-Datenbank ab. Gelöschte/geschlossene Objekte werden automatisch ausgeschlossen.',
                position: 'bottom'
            },
            {
                selector: '#btnCreateBatch',
                text: 'Erstellt den Batch: Liest DMS-Objekte, wendet Filter/Ausschlüsse an, generiert Ziel-Dokumentennummern.',
                position: 'top'
            }
        ],

        // ── Mapping ──────────────────────────────────────────────────
        mapping: [
            {
                selector: '#btnDownloadTemplate',
                text: 'Excel-Template mit Tabellenblättern: Mappings, Batch Objects, Unmapped, Info. Füllen Sie die Ziel-Spalten aus.',
                position: 'bottom'
            },
            {
                selector: '#btnStartLinking',
                text: 'Erstellt Objekt-Verknüpfungen im Zielsystem. Nur für Datensätze mit Status "success" und erstelltem Container.',
                position: 'bottom'
            }
        ],

        // ── Settings ─────────────────────────────────────────────────
        settings: [
            {
                selector: '#maxWorkers',
                text: 'Anzahl paralleler API-Aufrufe (1–50). Mehr = schneller, aber höhere Last auf dem Zielsystem. Standard: 7',
                position: 'right'
            },
            {
                selector: '#pacing',
                text: '0 = Dynamisches Pacing (empfohlen): Passt Verzögerung automatisch an Dateigröße an. Fester Wert = konstante Verzögerung in Sekunden.',
                position: 'right'
            }
        ]
    };

    // ── State ────────────────────────────────────────────────────────
    let activeTooltip = null;
    let tooltipTimeout = null;
    let attachedElements = [];
    let stylesInjected = false;

    // ── Page Detection ───────────────────────────────────────────────
    function detectPage() {
        const path = window.location.pathname;
        if (path === '/' || path === '/index')    return 'dashboard';
        if (path === '/settings')                  return 'settings';
        if (path === '/prepare')                   return 'prepare';
        if (path.includes('/preview'))             return 'preview';
        if (path.includes('/object-mapping'))       return 'mapping';
        if (path.includes('/details'))             return 'details';
        if (path.includes('/wave-overview'))        return 'waves';
        return 'dashboard';
    }

    // ── Inject Styles ────────────────────────────────────────────────
    function injectStyles() {
        if (stylesInjected) return;
        stylesInjected = true;

        const style = document.createElement('style');
        style.textContent = `
            /* ── Inline Help Icon ─────────────────────────────────── */
            .inline-help-icon {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                width: 16px;
                height: 16px;
                border-radius: 50%;
                background: #e9ecef;
                color: #6c757d;
                font-size: 10px;
                font-weight: 700;
                cursor: help;
                margin-left: 4px;
                vertical-align: middle;
                transition: all 0.2s ease;
                border: 1px solid #dee2e6;
                flex-shrink: 0;
                line-height: 1;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                font-style: normal;
            }
            .inline-help-icon:hover {
                background: #004a96;
                color: #fff;
                border-color: #004a96;
                transform: scale(1.15);
            }

            /* ── Tooltip ──────────────────────────────────────────── */
            .inline-help-tooltip {
                position: fixed;
                z-index: 10010;
                max-width: 320px;
                min-width: 180px;
                padding: 10px 14px;
                background: #1a1a2e;
                color: #e8e8e8;
                font-size: 12.5px;
                line-height: 1.55;
                border-radius: 8px;
                box-shadow: 0 8px 24px rgba(0,0,0,0.25);
                pointer-events: none;
                opacity: 0;
                transform: translateY(4px);
                transition: opacity 0.2s ease, transform 0.2s ease;
                white-space: pre-line;
            }
            .inline-help-tooltip.visible {
                opacity: 1;
                transform: translateY(0);
                pointer-events: auto;
            }
            .inline-help-tooltip b {
                color: #82b1ff;
            }

            /* ── Arrow ────────────────────────────────────────────── */
            .inline-help-tooltip::before {
                content: '';
                position: absolute;
                width: 8px;
                height: 8px;
                background: #1a1a2e;
                transform: rotate(45deg);
            }
            .inline-help-tooltip.arrow-top::before {
                top: -4px;
                left: 20px;
            }
            .inline-help-tooltip.arrow-bottom::before {
                bottom: -4px;
                left: 20px;
            }
            .inline-help-tooltip.arrow-left::before {
                left: -4px;
                top: 12px;
            }
            .inline-help-tooltip.arrow-right::before {
                right: -4px;
                top: 12px;
            }

            /* ── Data-attribute based inline help ─────────────────── */
            [data-inline-help] {
                cursor: help;
                border-bottom: 1px dotted #6c757d;
            }

            /* ── Print: hide ──────────────────────────────────────── */
            @media print {
                .inline-help-icon, .inline-help-tooltip { display: none !important; }
            }
        `;
        document.head.appendChild(style);
    }

    // ── Create Tooltip Element ───────────────────────────────────────
    function getTooltipEl() {
        let el = document.getElementById('inlineHelpTooltip');
        if (!el) {
            el = document.createElement('div');
            el.id = 'inlineHelpTooltip';
            el.className = 'inline-help-tooltip';
            document.body.appendChild(el);
        }
        return el;
    }

    // ── Position Tooltip ─────────────────────────────────────────────
    function positionTooltip(tooltip, anchor, preferredPos) {
        const rect = anchor.getBoundingClientRect();
        const tw = tooltip.offsetWidth;
        const th = tooltip.offsetHeight;
        const gap = 8;
        const vw = window.innerWidth;
        const vh = window.innerHeight;

        // Remove all arrow classes
        tooltip.className = 'inline-help-tooltip visible';

        let top, left;

        if (preferredPos === 'top' && rect.top > th + gap) {
            top = rect.top - th - gap;
            left = rect.left + rect.width / 2 - tw / 2;
            tooltip.classList.add('arrow-bottom');
        } else if (preferredPos === 'right' && rect.right + tw + gap < vw) {
            top = rect.top + rect.height / 2 - th / 2;
            left = rect.right + gap;
            tooltip.classList.add('arrow-left');
        } else if (preferredPos === 'left' && rect.left > tw + gap) {
            top = rect.top + rect.height / 2 - th / 2;
            left = rect.left - tw - gap;
            tooltip.classList.add('arrow-right');
        } else {
            // Default: bottom
            top = rect.bottom + gap;
            left = rect.left + rect.width / 2 - tw / 2;
            tooltip.classList.add('arrow-top');
        }

        // Keep within viewport
        if (left < 8) left = 8;
        if (left + tw > vw - 8) left = vw - tw - 8;
        if (top < 8) top = 8;
        if (top + th > vh - 8) top = vh - th - 8;

        tooltip.style.top = top + 'px';
        tooltip.style.left = left + 'px';
    }

    // ── Show / Hide ──────────────────────────────────────────────────
    function showTooltip(anchor, text, position) {
        clearTimeout(tooltipTimeout);
        const tooltip = getTooltipEl();
        tooltip.innerHTML = formatText(text);

        // Position after content is set (need dimensions)
        tooltip.style.visibility = 'hidden';
        tooltip.classList.add('visible');
        requestAnimationFrame(() => {
            positionTooltip(tooltip, anchor, position || 'bottom');
            tooltip.style.visibility = '';
        });

        activeTooltip = { anchor, text, position };
    }

    function hideTooltip() {
        tooltipTimeout = setTimeout(() => {
            const tooltip = getTooltipEl();
            tooltip.classList.remove('visible');
            activeTooltip = null;
        }, 100);
    }

    function formatText(text) {
        // Convert ■ color markers and basic formatting
        return text
            .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
            .replace(/\n/g, '<br>');
    }

    // ── Attach Help Icon to Element ──────────────────────────────────
    function attachIcon(element, text, position) {
        // Don't attach twice
        if (element.dataset.inlineHelpAttached) return;
        element.dataset.inlineHelpAttached = 'true';

        const icon = document.createElement('span');
        icon.className = 'inline-help-icon';
        icon.innerHTML = '?';
        icon.title = '';

        icon.addEventListener('mouseenter', function(e) {
            e.stopPropagation();
            showTooltip(icon, text, position);
        });
        icon.addEventListener('mouseleave', function() {
            hideTooltip();
        });
        icon.addEventListener('click', function(e) {
            e.stopPropagation();
            e.preventDefault();
            // Toggle on click for mobile
            if (activeTooltip && activeTooltip.anchor === icon) {
                hideTooltip();
            } else {
                showTooltip(icon, text, position);
            }
        });

        // Insert icon after the element or inside it (depending on type)
        if (element.tagName === 'BUTTON' || element.tagName === 'A' ||
            element.tagName === 'INPUT' || element.tagName === 'SELECT') {
            // Insert after the element
            element.parentNode.insertBefore(icon, element.nextSibling);
        } else {
            // Append inside the element
            element.appendChild(icon);
        }

        attachedElements.push({ element, icon, text, position });
    }

    // ── Attach data-attribute based tooltips ─────────────────────────
    function attachDataAttributes() {
        document.querySelectorAll('[data-inline-help]').forEach(el => {
            if (el.dataset.inlineHelpAttached) return;
            const text = el.getAttribute('data-inline-help');
            const pos = el.getAttribute('data-help-position') || 'bottom';

            el.dataset.inlineHelpAttached = 'true';
            el.addEventListener('mouseenter', function() {
                showTooltip(el, text, pos);
            });
            el.addEventListener('mouseleave', function() {
                hideTooltip();
            });
        });
    }

    // ── Auto-attach for current page ─────────────────────────────────
    function autoAttach() {
        const page = detectPage();
        const defs = TOOLTIP_DEFS[page];
        if (!defs) return;

        defs.forEach(def => {
            if (def.attachTo === 'each') {
                document.querySelectorAll(def.selector).forEach(el => {
                    attachIcon(el, def.text, def.position);
                });
            } else {
                const el = document.querySelector(def.selector);
                if (el) {
                    attachIcon(el, def.text, def.position);
                }
            }
        });

        attachDataAttributes();
    }

    // ── Public API ───────────────────────────────────────────────────
    window.InlineHelp = {
        /**
         * Attach a tooltip to a specific element
         * @param {string|Element} selector - CSS selector or DOM element
         * @param {string} text - Tooltip text
         * @param {Object} [options] - { position: 'top'|'bottom'|'left'|'right' }
         */
        attach: function(selector, text, options) {
            const opts = options || {};
            const el = typeof selector === 'string' ? document.querySelector(selector) : selector;
            if (el) {
                attachIcon(el, text, opts.position || 'bottom');
            }
        },

        /**
         * Attach multiple tooltips at once
         * @param {Array} definitions - [{selector, text, position}]
         */
        attachMany: function(definitions) {
            definitions.forEach(def => {
                if (def.attachTo === 'each') {
                    document.querySelectorAll(def.selector).forEach(el => {
                        attachIcon(el, def.text, def.position || 'bottom');
                    });
                } else {
                    this.attach(def.selector, def.text, { position: def.position });
                }
            });
        },

        /**
         * Re-run auto-attach (call after dynamic DOM changes)
         */
        refreshAll: function() {
            autoAttach();
        },

        /**
         * Remove all attached tooltips
         */
        removeAll: function() {
            attachedElements.forEach(item => {
                if (item.icon && item.icon.parentNode) {
                    item.icon.parentNode.removeChild(item.icon);
                }
                if (item.element) {
                    delete item.element.dataset.inlineHelpAttached;
                }
            });
            attachedElements = [];
        },

        /**
         * Programmatically show tooltip on element
         */
        show: function(selector, text, position) {
            const el = typeof selector === 'string' ? document.querySelector(selector) : selector;
            if (el) showTooltip(el, text, position || 'bottom');
        },

        /**
         * Hide active tooltip
         */
        hide: function() {
            hideTooltip();
        }
    };

    // ── Init ─────────────────────────────────────────────────────────
    function init() {
        injectStyles();

        // Auto-attach after a short delay (let page JS render dynamic content)
        setTimeout(autoAttach, 800);

        // Re-attach when DOM changes (for dynamically loaded content)
        const observer = new MutationObserver(function(mutations) {
            let shouldRefresh = false;
            mutations.forEach(m => {
                if (m.addedNodes.length > 0) shouldRefresh = true;
            });
            if (shouldRefresh) {
                clearTimeout(observer._debounce);
                observer._debounce = setTimeout(autoAttach, 500);
            }
        });
        observer.observe(document.body, { childList: true, subtree: true });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
