/* Visual (WYSIWYG) place card editor.
 *
 * Renders the real print card inline, lets the user select/drag items, edit
 * them (or the card itself) in a side panel, set an anchor, and add fields.
 * All mutations POST to the server and swap the freshly rendered card back in.
 *
 * On drop, an item snaps to its nearest horizontal and vertical edge and the
 * distance to that edge is stored in h_align/v_align/h_pos/v_pos, keeping
 * hand-authored templates and the print path fully compatible.
 */
(function () {
    'use strict';

    let lastScale = 0;
    let patchTimer = null;
    let resizeObserver = null;
    let resizing = false;
    let lastSelect2Close = 0;

    function pxPerUnit(unit) { return unit === 'in' ? 96 : 96 / 25.4; }
    function clamp(v, min, max) { return Math.max(min, Math.min(max, v)); }
    function canvasEl() { return document.getElementById('place-card-canvas'); }

    function naturalCardSize(canvas) {
        // offsetWidth/Height are the layout size and ignore CSS transforms.
        // Width comes from a card face; height from the whole stack (a two-sided
        // editor view has two faces plus their labels/gaps).
        const wrapper = canvas.querySelector('.card-wrapper');
        const cards = canvas.querySelector('.cards-wrapper');
        return {
            width: wrapper ? wrapper.offsetWidth : 0,
            height: cards ? cards.offsetHeight : (wrapper ? wrapper.offsetHeight : 0),
        };
    }

    function applyScale(canvas, scale) {
        const stage = canvas.querySelector('.pc-canvas-stage');
        if (!stage) return;
        const natural = naturalCardSize(canvas);
        // Pin the stage to the card's natural size so, once scaled, it exactly
        // fills the canvas box (no phantom overflow to scroll into).
        stage.style.width = natural.width + 'px';
        stage.style.height = natural.height + 'px';
        stage.style.transform = 'scale(' + scale + ')';
        stage.style.transformOrigin = 'top left';
        canvas.style.width = natural.width * scale + 'px';
        canvas.style.height = natural.height * scale + 'px';
        canvas.dataset.scale = scale;
        lastScale = scale;
        try { sessionStorage.setItem('pc-scale-' + canvas.dataset.templateId, scale); } catch (e) { /* ignore */ }
        const label = document.getElementById('pc-zoom-label');
        if (label) label.textContent = Math.round(scale * 100) + '%';
        positionResizeHandle(canvas);
    }

    function savedScale(canvas) {
        try {
            const v = sessionStorage.getItem('pc-scale-' + canvas.dataset.templateId);
            return v ? parseFloat(v) : 0;
        } catch (e) { return 0; }
    }

    // Size the editor to the real visible width. The admin shell's --side-bar-width
    // var is contextual and --vw is set by JS on load, so a CSS calc() can be wrong;
    // measuring the sidebar's right edge is reliable.
    function fitEditor() {
        const editor = document.querySelector('.pc-editor');
        if (!editor) return;
        const sidebar = document.querySelector('.sidebar');
        const right = sidebar ? Math.round(sidebar.getBoundingClientRect().right) : 0;
        const width = Math.max(200, window.innerWidth - right);
        if (Math.abs((parseFloat(editor.style.width) || 0) - width) > 1) {
            editor.style.width = width + 'px';
        }
    }

    function centerView(canvas) {
        const host = canvas.closest('#pc-canvas-host');
        if (!host) return;
        host.scrollLeft = Math.max(0, (host.scrollWidth - host.clientWidth) / 2);
        host.scrollTop = Math.max(0, (host.scrollHeight - host.clientHeight) / 2);
    }

    // The admin shell sizes the host slightly after load (it sets --vw late).
    // A ResizeObserver re-centres exactly when the host's size settles - and on
    // window/panel resizes - but not on scroll or zoom, so it never fights the
    // user (zoom changes the canvas, not the host).
    function reflow() {
        const c = canvasEl();
        if (!c) return;
        fitEditor();
        // Re-apply the scale so the canvas box is (re)sized from a fresh
        // measurement - the very first init can measure the card as 0 before its
        // styles/layout are ready, which would otherwise stick until a zoom.
        applyScale(c, parseFloat(c.dataset.scale) || savedScale(c) || fitScale(c));
        centerView(c);
        if (window.PC_DEBUG || (window.localStorage && localStorage.getItem('pc-debug'))) {
            const host = c.closest('#pc-canvas-host');
            const editor = document.querySelector('.pc-editor');
            const sidebar = document.querySelector('.sidebar');
            console.log('[pc-editor] reflow', {
                innerW: window.innerWidth,
                sidebarRight: sidebar ? Math.round(sidebar.getBoundingClientRect().right) : null,
                editorW: editor ? Math.round(editor.getBoundingClientRect().width) : null,
                hostClientW: host ? host.clientWidth : null,
                hostScrollW: host ? host.scrollWidth : null,
                hostClientH: host ? host.clientHeight : null,
                hostScrollH: host ? host.scrollHeight : null,
                canvasW: Math.round(c.getBoundingClientRect().width),
                scrollLeft: host ? Math.round(host.scrollLeft) : null,
                scrollTop: host ? Math.round(host.scrollTop) : null,
            });
        }
    }

    function observeHost() {
        const host = document.getElementById('pc-canvas-host');
        if (!host || resizeObserver || typeof ResizeObserver === 'undefined') return;
        resizeObserver = new ResizeObserver(function () { reflow(); });
        resizeObserver.observe(host);
        // The sidebar width changes when compact mode is toggled; the host is
        // sized from the editor's own width, so observing only the host would
        // miss it. Watching the sidebar re-fits the editor on toggle.
        const sidebar = document.querySelector('.sidebar');
        if (sidebar) resizeObserver.observe(sidebar);
    }

    function settleCenter(canvas) {
        requestAnimationFrame(reflow);
        [0, 80, 200, 400, 700].forEach(function (delay) {
            setTimeout(function () { if (canvasEl() === canvas) reflow(); }, delay);
        });
    }

    function fitScale(canvas) {
        const natural = naturalCardSize(canvas);
        const host = canvas.closest('#pc-canvas-host') || canvas.parentElement;
        const avail = (host ? host.clientWidth : natural.width) - 48;
        let scale = natural.width > 0 ? Math.min(avail / natural.width, 4) : 2;
        if (!isFinite(scale) || scale <= 0) scale = 2;
        return scale;
    }

    function debouncedCall(fn, arg) {
        clearTimeout(patchTimer);
        patchTimer = setTimeout(function () { fn(arg); }, 300);
    }

    // ------------------------------------------------------------- panels

    function loadPanel(url) {
        const props = document.getElementById('pc-props');
        if (!url || !props) return;
        fetch(url).then(function (r) { return r.text(); }).then(function (html) {
            props.innerHTML = html;
            initContentBuilder();
        });
    }

    // Upload an image to the template's library, then reload the properties
    // panel so the new thumbnail appears (the user then clicks it to use it).
    function uploadImage(input) {
        const file = input.files && input.files[0];
        if (!file || !input.dataset.pcImageUpload) return;
        const form = new FormData();
        form.append('image', file);
        fetch(input.dataset.pcImageUpload, { method: 'POST', body: form })
            .then(function (r) { return r.text(); })
            .then(function (html) {
                const props = document.getElementById('pc-props');
                if (props) { props.innerHTML = html; initContentBuilder(); }
                // The server applied the upload to the item; re-render the canvas
                // so the selected node shows it.
                const form = document.getElementById('pc-props-form');
                if (form) onItemPatch(form);
            });
    }

    function selectImage(btn) {
        const hidden = document.getElementById('pc-image');
        if (!hidden) return;
        hidden.value = btn.dataset.pcImage;
        document.querySelectorAll('.pc-image-thumb').forEach(function (b) {
            b.classList.toggle('active', b === btn);
        });
        const form = document.getElementById('pc-props-form');
        if (form) debouncedCall(onItemPatch, form);
    }

    // Delete an image from the template library, then reload the panel so its
    // thumbnail disappears.
    function deleteImage(btn) {
        const url = btn.dataset.pcDeleteUrl;
        const name = btn.dataset.pcImageDelete;
        if (!url || !name) return;
        postForm(url, { image: name }).then(function (html) {
            const props = document.getElementById('pc-props');
            if (props) { props.innerHTML = html; initContentBuilder(); }
            // Re-render the canvas so any node that used the image (its
            // reference is now cleared server-side) shows the empty box.
            const form = document.getElementById('pc-props-form');
            if (form) onItemPatch(form);
        });
    }

    // ------------------------------------------------- content builder
    // A text item's content is an ordered list of "parts": literal text, or a
    // field (an expression with an optional prefix/suffix that only show when the
    // field has a value). The parts are serialised to Jinja on the server; here
    // we just manage the list of native inputs and post the parts as JSON.

    function contentEl() { return document.getElementById('pc-content'); }

    // Grow a textarea to fit its content (no inner scrollbar).
    function autosizeTextarea(ta) {
        ta.style.height = 'auto';
        ta.style.height = ta.scrollHeight + 'px';
    }

    function initContentBuilder() {
        // Code boxes (Custom CSS, raw Jinja) auto-size on load - do this before
        // the content-builder early-return so image/advanced panels get it too.
        const props = document.getElementById('pc-props');
        if (props) props.querySelectorAll('textarea.pc-code').forEach(autosizeTextarea);
        const root = contentEl();
        if (!root) return;
        // Each field row's <select> carries its expression in data-value (so the
        // same option markup can be cloned for new rows); apply it, adding a
        // custom option when a hand-authored expression is not in the list.
        root.querySelectorAll('.pc-part-expr').forEach(function (sel) {
            setSelectValue(sel, sel.dataset.value || '');
            initFieldSelect(sel);
        });
        // The font picker is another panel select loaded via innerHTML, so it
        // needs the same manual select2 init (and a search box for long lists).
        const fontSel = document.getElementById('pc-font-family');
        if (fontSel) initFieldSelect(fontSel);
        // Drag-to-reorder with the same SortableJS used across the admin.
        if (window.Sortable) {
            if (root._sortable) { try { root._sortable.destroy(); } catch (e) { /* ignore */ } }
            root._sortable = new window.Sortable(root, {
                animation: 150,
                handle: '.pc-part-drag',
                ghostClass: 'sortable-ghost',
                onEnd: pushContent,
            });
        }
        collectContent();
    }

    // The field selects live in client-cloned rows loaded via innerHTML, so the
    // usual inline-<script> select2 init (which only runs on an htmx swap) never
    // fires for them - initialise here with the same app-wide config.
    function initFieldSelect(sel) {
        if (!window.jQuery || !window.jQuery.fn || !window.jQuery.fn.select2) return;
        if (sel.classList.contains('select2-hidden-accessible')) return;
        const $sel = window.jQuery(sel);
        $sel.select2({
            theme: 'bootstrap-5',
            width: '100%',
            minimumResultsForSearch: 8,
        });
        // select2 fires its change through jQuery, which the native document
        // change-listener never hears; bridge it to a native input event so the
        // selection actually patches the item.
        $sel.on('change', function () {
            sel.dispatchEvent(new Event('input', { bubbles: true }));
        });
        // Note when a dropdown closes so the click that dismissed it isn't also
        // treated as a click on the canvas that deselects the item.
        $sel.on('select2:close', function () { lastSelect2Close = Date.now(); });
    }

    function setSelectValue(sel, value) {
        if (value && !Array.prototype.some.call(sel.options, function (o) { return o.value === value; })) {
            const opt = document.createElement('option');
            opt.value = value;
            opt.textContent = value;
            sel.appendChild(opt);
        }
        sel.value = value;
    }

    // Read the DOM rows into the hidden "content" field as a JSON parts array.
    function collectContent() {
        const root = contentEl();
        if (!root) return;
        const parts = [];
        root.querySelectorAll('.pc-part').forEach(function (row) {
            if (row.dataset.part === 't') {
                parts.push({ k: 't', v: row.querySelector('.pc-part-text').value });
            } else {
                parts.push({
                    k: 'f',
                    e: row.querySelector('.pc-part-expr').value,
                    p: row.querySelector('.pc-part-prefix').value,
                    s: row.querySelector('.pc-part-suffix').value,
                });
            }
        });
        const hidden = document.querySelector('#pc-props-form input[name="content"]');
        if (hidden) hidden.value = JSON.stringify(parts);
    }

    function addPart(kind) {
        const root = contentEl();
        const tplId = { t: 'pc-part-text-tpl', f: 'pc-part-field-tpl' }[kind];
        const tpl = document.getElementById(tplId);
        if (!root || !tpl) return;
        const row = tpl.content.firstElementChild.cloneNode(true);
        root.appendChild(row);
        const expr = row.querySelector('.pc-part-expr');
        if (expr) initFieldSelect(expr);
        const focusable = row.querySelector('input, select');
        if (focusable) focusable.focus();
        pushContent();
    }

    function removePart(row) {
        row.remove();
        pushContent();
    }

    // Recompute the parts JSON and push the change to the server (live preview).
    function pushContent() {
        collectContent();
        const form = document.getElementById('pc-props-form');
        if (form) debouncedCall(onItemPatch, form);
    }

    // ------------------------------------------------------------- fill
    // The visible fill swatch is our own span; the native colour input on top is
    // invisible. A hidden field carries the value so an empty string can mean
    // "no fill" (native colour inputs can never be empty).
    function fillEls() {
        const input = document.getElementById('pc-bg-color');
        const span = input ? input.closest('.pc-swatch') : null;
        return {
            span: span,
            hidden: span ? span.querySelector('input[name="background_color"]') : null,
            clear: document.querySelector('[data-pc-fill-clear]'),
        };
    }
    function applyFillColor(color) {
        const e = fillEls();
        if (e.hidden) e.hidden.value = color;
        if (e.span) { e.span.style.background = color; e.span.classList.remove('pc-fill-empty'); }
        if (e.clear) e.clear.classList.remove('d-none');
    }
    function clearFill() {
        const e = fillEls();
        if (e.span) { e.span.style.background = ''; e.span.classList.add('pc-fill-empty'); }
        if (e.clear) e.clear.classList.add('d-none');
        if (e.hidden) { e.hidden.value = ''; e.hidden.dispatchEvent(new Event('input', { bubbles: true })); }
    }

    function showItemPanel(canvas, section, mode) {
        loadPanel(
            canvas.dataset.propsUrl + '?section=' + encodeURIComponent(section)
            + (mode ? '&mode=' + mode : '')
        );
    }
    function showCardPanel(canvas) {
        loadPanel(canvas.dataset.cardPropsUrl);
    }

    function highlightOnly(canvas, section) {
        canvas.querySelectorAll('.card-item.pc-selected').forEach(function (el) {
            el.classList.remove('pc-selected');
        });
        canvas.dataset.selected = section || '';
        if (section) {
            const wrap = canvas.querySelector('.pc-edit-item[data-section="' + section + '"]');
            const item = wrap && wrap.querySelector('.card-item');
            if (item) item.classList.add('pc-selected');
            positionResizeHandle(canvas);
        } else {
            hideResizeHandle();
        }
    }

    // The face (two-sided cards only) whose box contains the pointer, or null.
    // Faces never overlap, so the first hit is the answer.
    function faceAtPoint(canvas, x, y) {
        for (const face of canvas.querySelectorAll('.pc-side')) {
            const r = face.getBoundingClientRect();
            if (x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) return face;
        }
        return null;
    }

    function undimSides(canvas) {
        canvas.querySelectorAll('.pc-side.pc-dim').forEach(function (s) {
            s.classList.remove('pc-dim');
        });
    }

    function updateSideDim(canvas) {
        const active = canvas.dataset.activeSide;
        canvas.querySelectorAll('.pc-side').forEach(function (s) {
            s.classList.toggle('pc-dim', !!active && s.dataset.side !== active);
        });
    }

    // Select an item (or, with null, the card). withPanel reloads the side panel.
    // Selecting an item also sets the active side (where new items are placed)
    // and dims the other face. Deselecting only clears the dimming.
    function selectItem(canvas, item, withPanel) {
        if (!item) {
            highlightOnly(canvas, '');
            undimSides(canvas);
            if (withPanel) showCardPanel(canvas);
            return;
        }
        const wrap = item.closest('.pc-edit-item');
        const section = wrap ? wrap.dataset.section : '';
        highlightOnly(canvas, section);
        const face = wrap ? wrap.closest('.pc-side') : null;
        if (face) {
            canvas.dataset.activeSide = face.dataset.side;
            updateSideDim(canvas);
        }
        if (withPanel) showItemPanel(canvas, section);
    }

    // ------------------------------------------------------------ server I/O

    function postForm(url, params) {
        // Carry the current sample-data example on every canvas request so
        // re-renders keep showing the same example.
        const c = canvasEl();
        if (c && params && params.example === undefined) {
            params.example = c.dataset.example || '0';
        }
        return fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams(params),
        }).then(function (r) { return r.text(); });
    }

    function onExample(index) {
        const c = canvasEl();
        if (c) postForm(c.dataset.exampleUrl, { example: index }).then(function (h) { swapCanvas(h, true); });
    }

    function formParams(form) {
        const params = {};
        new FormData(form).forEach(function (value, key) { params[key] = value; });
        return params;
    }

    // keepPanel: leave the side panel untouched (used while editing in it).
    function swapCanvas(html, keepPanel) {
        const current = canvasEl();
        if (!current) return;
        const host = current.closest('#pc-canvas-host');
        const scrollLeft = host ? host.scrollLeft : 0;
        const scrollTop = host ? host.scrollTop : 0;
        const carried = current.dataset.selected || '';
        const carriedSide = current.dataset.activeSide || '';
        const holder = document.createElement('template');
        holder.innerHTML = html.trim();
        const fresh = holder.content.firstElementChild;
        if (!fresh) return;
        current.replaceWith(fresh);
        initCanvas(fresh);
        updateHistoryButtons();
        if (host) { host.scrollLeft = scrollLeft; host.scrollTop = scrollTop; }
        if (carriedSide) {
            fresh.dataset.activeSide = carriedSide;
            updateSideDim(fresh);
        }
        const explicit = fresh.dataset.pcSelect;
        if (explicit) {
            const wrap = fresh.querySelector('.pc-edit-item[data-section="' + explicit + '"]');
            selectItem(fresh, wrap ? wrap.querySelector('.card-item') : null, true);
        } else if (keepPanel) {
            highlightOnly(fresh, carried);
        } else if (carried && fresh.querySelector('.pc-edit-item[data-section="' + carried + '"]')) {
            highlightOnly(fresh, carried);
        } else {
            selectItem(fresh, null, true); // deselected -> card panel
        }
    }

    function onAdd(kind) {
        const c = canvasEl();
        if (c) postForm(c.dataset.addUrl, { kind: kind, side: c.dataset.activeSide || 'front' }).then(function (h) { swapCanvas(h); });
    }
    function onAddField(token) {
        const c = canvasEl();
        if (c) postForm(c.dataset.addFieldUrl, { token: token, side: c.dataset.activeSide || 'front' }).then(function (h) { swapCanvas(h); });
    }
    function onDelete(section) {
        const c = canvasEl();
        if (c && section) postForm(c.dataset.deleteUrl, { section: section }).then(function (h) { swapCanvas(h); });
    }
    function onUndo() {
        const c = canvasEl();
        if (c && c.dataset.canUndo) postForm(c.dataset.undoUrl, {}).then(function (h) { swapCanvas(h, true); refreshOpenPanel(); });
    }
    function onRedo() {
        const c = canvasEl();
        if (c && c.dataset.canRedo) postForm(c.dataset.redoUrl, {}).then(function (h) { swapCanvas(h, true); refreshOpenPanel(); });
    }
    // After undo/redo the file may have changed the current item or card
    // settings (e.g. the two-sided switch); reload the open side panel so it is
    // not left showing stale values.
    function refreshOpenPanel() {
        const c = canvasEl();
        if (!c) return;
        const sel = c.dataset.selected;
        if (sel && c.querySelector('.pc-edit-item[data-section="' + sel + '"]')) {
            showItemPanel(c, sel);
        } else {
            showCardPanel(c);
        }
    }
    // Reflect the server's history state on the toolbar buttons after each swap.
    function updateHistoryButtons() {
        const c = canvasEl();
        const undoBtn = document.querySelector('[data-pc-undo]');
        const redoBtn = document.querySelector('[data-pc-redo]');
        if (undoBtn) undoBtn.disabled = !(c && c.dataset.canUndo);
        if (redoBtn) redoBtn.disabled = !(c && c.dataset.canRedo);
    }
    function onItemPatch(form) {
        const c = canvasEl();
        if (c) postForm(c.dataset.patchUrl, formParams(form)).then(function (h) { swapCanvas(h, true); });
    }
    function onCardPatch(form, reloadPanel) {
        const c = canvasEl();
        if (!c) return;
        postForm(c.dataset.cardPatchUrl, formParams(form)).then(function (h) {
            swapCanvas(h, true);
            // The unit switch converts every length: reload the panel so its
            // fields show the converted values and get the matching step.
            if (reloadPanel) {
                const fresh = canvasEl();
                if (fresh) showCardPanel(fresh);
            }
        });
    }

    function onAnchor() {
        const c = canvasEl();
        const grid = document.getElementById('pc-anchor');
        const checked = grid && grid.querySelector('input[name="anchor"]:checked');
        if (!c || !grid || !checked) return;
        const parts = checked.value.split(':');
        const section = grid.dataset.section;
        postForm(c.dataset.anchorUrl, {
            section: section, h_align: parts[0], v_align: parts[1],
        }).then(function (h) {
            swapCanvas(h, true);
            showItemPanel(canvasEl(), section); // refresh offset labels / disabled state
        });
    }

    // Stacking is the item's order in the file: reordering re-renders the card.
    function onReorder(where) {
        const c = canvasEl();
        const block = document.getElementById('pc-stacking');
        if (!c || !block) return;
        postForm(c.dataset.reorderUrl, { section: block.dataset.section, where: where })
            .then(function (h) { swapCanvas(h, true); });
    }

    function onOffset() {
        const c = canvasEl();
        const grid = document.getElementById('pc-anchor');
        const checked = grid && grid.querySelector('input[name="anchor"]:checked');
        if (!c || !grid || !checked) return;
        const parts = checked.value.split(':');
        const hEl = document.getElementById('pc-h-pos');
        const vEl = document.getElementById('pc-v-pos');
        postForm(c.dataset.moveUrl, {
            section: grid.dataset.section,
            h_align: parts[0], v_align: parts[1],
            h_pos: parts[0] === 'center' ? '0' : (hEl ? hEl.value || '0' : '0'),
            v_pos: parts[1] === 'middle' ? '0' : (vEl ? vEl.value || '0' : '0'),
        }).then(function (h) { swapCanvas(h, true); });
    }

    // ------------------------------------------------------------------ drag

    // Offset measured from the item's CURRENT anchor (dragging never changes
    // which anchor is used - that is set only via the anchor picker). Offsets
    // are NOT clamped: an item may overflow the card edge (printing clips it, the
    // editor keeps it visible and selectable so it can be dragged back).
    function offsetFor(canvas, wrap, contentRect, itemLeftVp, itemTopVp, itemWvp, itemHvp) {
        const scale = parseFloat(canvas.dataset.scale) || 1;
        const ppu = pxPerUnit(canvas.dataset.unit || 'mm');
        const hAlign = wrap.dataset.hAlign || 'left';
        const vAlign = wrap.dataset.vAlign || 'top';
        const contentW = contentRect.width / scale;
        const contentH = contentRect.height / scale;
        const itemW = itemWvp / scale;
        const itemH = itemHvp / scale;
        const left = (itemLeftVp - contentRect.left) / scale;
        const top = (itemTopVp - contentRect.top) / scale;
        const right = contentW - itemW - left;
        const bottom = contentH - itemH - top;
        const hPos = hAlign === 'center' ? 0 : (hAlign === 'right' ? right : left);
        const vPos = vAlign === 'middle' ? 0 : (vAlign === 'bottom' ? bottom : top);
        return { hAlign: hAlign, vAlign: vAlign, hPos: hPos / ppu, vPos: vPos / ppu };
    }

    function showBadge(a, unit, x, y) {
        const el = document.getElementById('pc-drag-badge');
        if (!el) return;
        const hl = a.hAlign === 'center' ? '↔' : (a.hAlign === 'left' ? '←' : '→');
        const vl = a.vAlign === 'middle' ? '↕' : (a.vAlign === 'top' ? '↑' : '↓');
        // A centred/middled axis is locked - show a padlock instead of the offset.
        const lock = '<i class="bi-lock-fill"></i>';
        const hStr = a.hAlign === 'center' ? lock : a.hPos.toFixed(1) + unit;
        const vStr = a.vAlign === 'middle' ? lock : a.vPos.toFixed(1) + unit;
        el.innerHTML = hl + ' ' + hStr + '   ' + vl + ' ' + vStr;
        el.style.left = x + 14 + 'px';
        el.style.top = y + 14 + 'px';
        el.style.display = 'block';
    }
    function hideBadge() {
        const el = document.getElementById('pc-drag-badge');
        if (el) el.style.display = 'none';
    }

    // -------------------------------------------------------- width resize

    // The selected item that carries a width (text and image), or null. The
    // width resize knob attaches to these.
    function selectedTextItem(canvas) {
        const section = canvas && canvas.dataset.selected;
        if (!section) return null;
        const wrap = canvas.querySelector('.pc-edit-item[data-section="' + section + '"]');
        if (!wrap || (wrap.dataset.kind !== 'text' && wrap.dataset.kind !== 'image')) return null;
        return { wrap: wrap, item: wrap.querySelector('.card-item') };
    }

    // Put the resize knob on the item's far edge (the side away from its anchor).
    function positionResizeHandle(canvas) {
        const handle = document.getElementById('pc-resize-handle');
        if (!handle) return;
        const sel = canvas && selectedTextItem(canvas);
        if (!sel || !sel.item || resizing) return;
        const rect = sel.item.getBoundingClientRect();
        const edgeX = sel.wrap.dataset.hAlign === 'right' ? rect.left : rect.right;
        handle.style.left = edgeX + 'px';
        handle.style.top = (rect.top + rect.height / 2) + 'px';
        // Filled once the item has an explicit width; hollow while auto-sized.
        handle.classList.toggle('pc-set', !!sel.wrap.dataset.width);
        handle.style.display = 'block';
    }
    function hideResizeHandle() {
        const handle = document.getElementById('pc-resize-handle');
        if (handle) handle.style.display = 'none';
    }

    function startResize(event) {
        const canvas = canvasEl();
        const sel = canvas && selectedTextItem(canvas);
        if (!sel || !sel.item) return;
        event.preventDefault();
        event.stopPropagation();
        resizing = true;
        const item = sel.item;
        const scale = parseFloat(canvas.dataset.scale) || 1;
        const unit = canvas.dataset.unit || 'mm';
        const ppu = pxPerUnit(unit);
        const wrap = sel.wrap;
        const anchor = wrap.dataset.hAlign;
        const startWidth = item.getBoundingClientRect().width / scale / ppu;
        const startX = event.clientX;
        const input = document.getElementById('pc-width');
        const handle = event.currentTarget;
        try { handle.setPointerCapture(event.pointerId); } catch (e) { /* ignore */ }

        function onMove(ev) {
            let delta = (ev.clientX - startX) / scale / ppu;
            if (anchor === 'right') delta = -delta;   // handle is on the left edge
            else if (anchor === 'center') delta *= 2; // grows symmetrically
            const width = Math.max(1, startWidth + delta);
            item.style.width = width.toFixed(1) + unit;
            if (input) input.value = width.toFixed(1);
            wrap.dataset.width = width.toFixed(1); // outline -> solid, live
            handle.classList.add('pc-set');
            handle.style.left = ev.clientX + 'px';
            const badge = document.getElementById('pc-drag-badge');
            if (badge) {
                badge.textContent = '↔ ' + width.toFixed(1) + unit;
                badge.style.left = (ev.clientX + 14) + 'px';
                badge.style.top = (ev.clientY + 14) + 'px';
                badge.style.display = 'block';
            }
        }
        function onUp() {
            handle.removeEventListener('pointermove', onMove);
            handle.removeEventListener('pointerup', onUp);
            resizing = false;
            hideBadge();
            const form = document.getElementById('pc-props-form');
            if (form) onItemPatch(form); // persist width + re-render
        }
        handle.addEventListener('pointermove', onMove);
        handle.addEventListener('pointerup', onUp);
    }

    // All the items overlapping the pointer, topmost first (the event only
    // reaches the topmost, but hidden ones must stay reachable).
    function itemsAtPoint(event) {
        return document.elementsFromPoint(event.clientX, event.clientY)
            .filter(function (el) {
                return el.classList && el.classList.contains('card-item');
            });
    }

    function startDrag(event, canvas, item) {
        if (event.button !== undefined && event.button !== 0) return;
        event.preventDefault();
        // Overlapping-item handling: if the already-selected item is under the
        // pointer, keep it (so an item hidden beneath others stays draggable and
        // resizable); otherwise grab the topmost. A plain click - no drag - on
        // the selected item then cycles down to the next one so hidden items can
        // be reached.
        const stack = itemsAtPoint(event);
        const selected = canvas.querySelector('.card-item.pc-selected');
        const selectedInStack = selected && stack.indexOf(selected) !== -1;
        item = selectedInStack ? selected : (stack[0] || item);
        const cycleOnClick = selectedInStack && stack.length > 1;
        selectItem(canvas, item, true);
        // Measure against the item's own face (a two-sided card has two).
        const content = item.closest('.card-content');
        if (!content) return;
        // Two-sided cards: dropping on the other face moves the item there.
        // The source face is lifted so the dragged item stays on top of the
        // other one instead of sliding behind it, and both faces are undimmed
        // so the target is visible while dragging.
        const startFace = item.closest('.pc-side');
        let dropFace = startFace;
        if (startFace) {
            startFace.classList.add('pc-drag-source');
            undimSides(canvas);
        }
        function dropContent() {
            return (dropFace && dropFace.querySelector('.card-content')) || content;
        }
        function clearFaceMarks() {
            canvas.querySelectorAll('.pc-drag-source, .pc-drop-target').forEach(
                function (face) {
                    face.classList.remove('pc-drag-source', 'pc-drop-target');
                });
        }
        const unit = canvas.dataset.unit || 'mm';
        const wrap = item.closest('.pc-edit-item');
        const startRect = item.getBoundingClientRect();
        // A centred item carries a translateX/Y(-50%) transform; keep it as the
        // base so the drag delta adds to it instead of wiping out the centring.
        const computedTransform = getComputedStyle(item).transform;
        const baseTransform = computedTransform && computedTransform !== 'none'
            ? computedTransform + ' ' : '';
        const scale = parseFloat(canvas.dataset.scale) || 1;
        const startX = event.clientX, startY = event.clientY;
        let dx = 0, dy = 0, moved = false;
        item.classList.add('pc-dragging');
        try { item.setPointerCapture(event.pointerId); } catch (e) { /* ignore */ }

        function liveOffset(a) {
            const hEl = document.getElementById('pc-h-pos');
            const vEl = document.getElementById('pc-v-pos');
            if (hEl && !hEl.disabled) hEl.value = a.hPos.toFixed(1);
            if (vEl && !vEl.disabled) vEl.value = a.vPos.toFixed(1);
        }

        function onMove(ev) {
            // A centred axis is locked - dragging only moves the free axis.
            dx = wrap.dataset.hAlign === 'center' ? 0 : (ev.clientX - startX);
            dy = wrap.dataset.vAlign === 'middle' ? 0 : (ev.clientY - startY);
            if (Math.abs(dx) + Math.abs(dy) > 2) moved = true;
            if (moved) hideResizeHandle(); // stale while the item moves
            item.style.transform = baseTransform + 'translate(' + dx / scale + 'px,' + dy / scale + 'px)';
            const face = faceAtPoint(canvas, ev.clientX, ev.clientY) || startFace;
            if (face !== dropFace) {
                if (dropFace) dropFace.classList.remove('pc-drop-target');
                dropFace = face;
                if (dropFace && dropFace !== startFace) {
                    dropFace.classList.add('pc-drop-target');
                }
            }
            const a = offsetFor(canvas, wrap, dropContent().getBoundingClientRect(),
                startRect.left + dx, startRect.top + dy, startRect.width, startRect.height);
            showBadge(a, unit, ev.clientX, ev.clientY);
            liveOffset(a);
        }
        function onUp() {
            item.removeEventListener('pointermove', onMove);
            item.removeEventListener('pointerup', onUp);
            item.classList.remove('pc-dragging');
            hideBadge();
            if (!moved) {
                clearFaceMarks();
                updateSideDim(canvas);
                item.style.transform = '';
                // A plain click on the selected item in a stack steps to the
                // next one down, cycling through overlapping items.
                if (cycleOnClick) {
                    const idx = stack.indexOf(item);
                    selectItem(canvas, stack[(idx + 1) % stack.length], true);
                }
                return;
            }
            // Keep the dragged transform until the re-render swaps the canvas in,
            // so the item doesn't flash back to its old position first.
            const a = offsetFor(canvas, wrap, dropContent().getBoundingClientRect(),
                startRect.left + dx, startRect.top + dy, startRect.width, startRect.height);
            const params = {
                section: wrap.dataset.section,
                h_align: a.hAlign, v_align: a.vAlign,
                h_pos: a.hPos.toFixed(2), v_pos: a.vPos.toFixed(2),
            };
            if (dropFace && startFace && dropFace !== startFace) {
                params.side = dropFace.dataset.side;
                canvas.dataset.activeSide = dropFace.dataset.side;
            }
            clearFaceMarks();
            postForm(canvas.dataset.moveUrl, params)
                .then(function (h) { swapCanvas(h, true); });
        }
        item.addEventListener('pointermove', onMove);
        item.addEventListener('pointerup', onUp);
    }

    // --------------------------------------------------------------- canvas

    function initCanvas(canvas) {
        if (!canvas || canvas.dataset.pcBound) return;
        const scale = canvas.dataset.scale
            ? parseFloat(canvas.dataset.scale)
            : (lastScale || savedScale(canvas) || fitScale(canvas));
        applyScale(canvas, scale);
        canvas.querySelectorAll('.pc-edit-item').forEach(function (wrap) {
            const item = wrap.querySelector('.card-item');
            if (!item) return;
            item.addEventListener('pointerdown', function (event) { startDrag(event, canvas, item); });
        });
        canvas.dataset.pcBound = '1';
    }

    const MIN_SCALE = 0.2, MAX_SCALE = 8;

    // Zoom keeping the point under the pointer where it is, the way a map does.
    function zoomAt(canvas, scale, clientX, clientY) {
        const host = canvas.closest('#pc-canvas-host');
        const oldScale = parseFloat(canvas.dataset.scale) || 1;
        scale = clamp(scale, MIN_SCALE, MAX_SCALE);
        if (!host || scale === oldScale) return;
        const before = canvas.getBoundingClientRect();
        // The pointer in unscaled card coordinates.
        const cx = (clientX - before.left) / oldScale;
        const cy = (clientY - before.top) / oldScale;
        applyScale(canvas, scale);
        // Where that point sits now; scrolling by the difference puts it back
        // under the pointer.
        const after = canvas.getBoundingClientRect();
        host.scrollLeft += after.left + cx * scale - clientX;
        host.scrollTop += after.top + cy * scale - clientY;
    }

    // A trackpad pinch reaches the page as a wheel event with ctrlKey set;
    // Ctrl/Cmd + wheel is the mouse equivalent. A plain wheel keeps scrolling.
    function onWheel(event) {
        if (!event.ctrlKey && !event.metaKey) return;
        const canvas = canvasEl();
        if (!canvas) return;
        event.preventDefault(); // ... and stop the browser zooming the page
        let delta = event.deltaY;
        if (event.deltaMode === 1) delta *= 16;  // lines, not pixels
        // A mouse wheel sends far bigger deltas than a pinch: capping keeps one
        // notch to a sane step without making the pinch feel sluggish.
        const factor = Math.exp(-clamp(delta, -30, 30) * 0.01);
        const scale = parseFloat(canvas.dataset.scale) || 1;
        zoomAt(canvas, scale * factor, event.clientX, event.clientY);
    }

    // Safari reports a pinch as its own gesture events rather than ctrl+wheel.
    let gestureScale = 1;
    function onGestureStart(event) {
        const canvas = canvasEl();
        if (!canvas) return;
        event.preventDefault();
        gestureScale = parseFloat(canvas.dataset.scale) || 1;
    }
    function onGestureChange(event) {
        const canvas = canvasEl();
        if (!canvas) return;
        event.preventDefault();
        zoomAt(canvas, gestureScale * event.scale, event.clientX, event.clientY);
    }

    function onZoom(dir) {
        const canvas = canvasEl();
        if (!canvas) return;
        let scale = parseFloat(canvas.dataset.scale) || 2;
        if (dir === 'in') scale *= 1.2;
        else if (dir === 'out') scale /= 1.2;
        else if (dir === 'fit') scale = fitScale(canvas);
        else scale = 1; // reset to 100%
        applyScale(canvas, clamp(scale, MIN_SCALE, MAX_SCALE));
        centerView(canvas);
    }

    // ------------------------------------------------------------- controls

    let boundControls = false;
    function bindControls() {
        if (boundControls) return;
        boundControls = true;
        observeHost();
        window.addEventListener('resize', reflow);
        const resizeHandle = document.getElementById('pc-resize-handle');
        if (resizeHandle) resizeHandle.addEventListener('pointerdown', startResize);
        // The handle is positioned in viewport coords, so it must follow scroll.
        const host = document.getElementById('pc-canvas-host');
        if (host) {
            host.addEventListener('scroll', function () {
                const c = canvasEl();
                if (c) positionResizeHandle(c);
            });
            host.addEventListener('wheel', onWheel, { passive: false });
            host.addEventListener('gesturestart', onGestureStart);
            host.addEventListener('gesturechange', onGestureChange);
        }
        document.addEventListener('click', function (event) {
            const zoom = event.target.closest('[data-pc-zoom]');
            if (zoom) { event.preventDefault(); onZoom(zoom.dataset.pcZoom); return; }
            const add = event.target.closest('[data-pc-add]');
            if (add) { event.preventDefault(); onAdd(add.dataset.pcAdd); return; }
            const field = event.target.closest('[data-pc-add-field]');
            if (field) { event.preventDefault(); onAddField(field.dataset.pcAddField); return; }
            const example = event.target.closest('[data-pc-example]');
            if (example) {
                event.preventDefault();
                example.parentNode.querySelectorAll('[data-pc-example]').forEach(function (b) { b.classList.remove('active'); });
                example.classList.add('active');
                onExample(example.dataset.pcExample);
                return;
            }
            const fillClear = event.target.closest('[data-pc-fill-clear]');
            if (fillClear) { event.preventDefault(); clearFill(); return; }
            const imageDel = event.target.closest('[data-pc-image-delete]');
            if (imageDel) { event.preventDefault(); deleteImage(imageDel); return; }
            const imageThumb = event.target.closest('[data-pc-image]');
            if (imageThumb) { event.preventDefault(); selectImage(imageThumb); return; }
            const undoBtn = event.target.closest('[data-pc-undo]');
            if (undoBtn) { event.preventDefault(); onUndo(); return; }
            const redoBtn = event.target.closest('[data-pc-redo]');
            if (redoBtn) { event.preventDefault(); onRedo(); return; }
            const boundsBtn = event.target.closest('[data-pc-bounds]');
            if (boundsBtn) {
                event.preventDefault();
                // The button is "on" when outlines are shown (default).
                const showing = boundsBtn.classList.toggle('active');
                boundsBtn.setAttribute('aria-pressed', showing ? 'true' : 'false');
                const host = document.getElementById('pc-canvas-host');
                if (host) host.classList.toggle('pc-hide-bounds', !showing);
                return;
            }
            const modeBtn = event.target.closest('[data-pc-mode]');
            if (modeBtn) {
                event.preventDefault();
                const c = canvasEl();
                if (c && c.dataset.selected) showItemPanel(c, c.dataset.selected, modeBtn.dataset.pcMode);
                return;
            }
            const reorderBtn = event.target.closest('[data-pc-reorder]');
            if (reorderBtn) {
                event.preventDefault();
                onReorder(reorderBtn.dataset.pcReorder);
                return;
            }
            const clearWidth = event.target.closest('[data-pc-clear-width]');
            if (clearWidth) {
                event.preventDefault();
                const input = document.getElementById('pc-width');
                if (input) { input.value = ''; input.dispatchEvent(new Event('input', { bubbles: true })); }
                return;
            }
            const addPartBtn = event.target.closest('[data-pc-add-part]');
            if (addPartBtn) { event.preventDefault(); addPart(addPartBtn.dataset.pcAddPart); return; }
            const affixToggle = event.target.closest('.pc-affix-toggle');
            if (affixToggle) {
                event.preventDefault();
                const part = affixToggle.closest('.pc-part');
                const affixes = part && part.querySelector('.pc-affixes');
                if (affixes) {
                    const shown = affixes.classList.toggle('d-none');
                    affixToggle.classList.toggle('active', !shown);
                }
                return;
            }
            const removeBtn = event.target.closest('.pc-part-remove');
            if (removeBtn) { event.preventDefault(); removePart(removeBtn.closest('.pc-part')); return; }
            const del = event.target.closest('[data-pc-delete]');
            if (del) {
                event.preventDefault();
                const c = canvasEl();
                if (c) onDelete(c.dataset.selected);
                return;
            }
            // A click in the canvas area that is not on an item: on a face's
            // background it activates that side (so new items land there) and
            // dims the other; on the grey outside any face it fully deselects.
            if (event.target.closest('#pc-canvas-host') && !event.target.closest('.card-item')) {
                const c = canvasEl();
                if (!c) return;
                // Ignore the click that just dismissed an open select2 dropdown -
                // the user meant to close the dropdown, not deselect the item.
                if (Date.now() - lastSelect2Close < 300) return;
                const face = event.target.closest('.pc-side');
                if (face) {
                    highlightOnly(c, '');
                    c.dataset.activeSide = face.dataset.side;
                    updateSideDim(c);
                    showCardPanel(c);
                } else {
                    selectItem(c, null, true);
                }
            }
        });
        document.addEventListener('keydown', function (event) {
            const editable = /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName || '')
                || event.target.isContentEditable;
            // Undo/redo (Ctrl/Cmd+Z, Ctrl/Cmd+Shift+Z or Ctrl+Y). Skip when a
            // field is focused so native text undo still works there.
            const mod = event.ctrlKey || event.metaKey;
            if (mod && !editable && canvasEl()) {
                const k = (event.key || '').toLowerCase();
                if (k === 'z' && !event.shiftKey) { event.preventDefault(); onUndo(); return; }
                if ((k === 'z' && event.shiftKey) || k === 'y') { event.preventDefault(); onRedo(); return; }
            }
            if ((event.key === 'Delete' || event.key === 'Backspace') &&
                !editable && canvasEl()) {
                event.preventDefault();
                onDelete(canvasEl().dataset.selected);
            }
        });
        function onFormEvent(event) {
            const t = event.target;
            // A file input fires both 'input' and 'change' on pick; upload once.
            if (t.matches('[data-pc-image-upload]')) { if (event.type === 'change') uploadImage(t); return; }
            if (t.closest('#pc-props-form')) {
                // Content-builder inputs: refresh the parts JSON before the patch
                // reads the form.
                if (t.closest('#pc-content')) collectContent();
                if (t.matches('textarea.pc-code')) autosizeTextarea(t);
                if (t.id === 'pc-bg-color') applyFillColor(t.value);
                // Live-update a plain colour swatch (text, border) as it changes.
                else if (t.matches('.pc-swatch input[type="color"]')) t.closest('.pc-swatch').style.background = t.value;
                debouncedCall(onItemPatch, t.closest('#pc-props-form'));
            }
            else if (t.closest('#pc-card-form')) {
                // Live-update the header title as the name is typed.
                if (t.id === 'pc-card-name') {
                    const title = document.getElementById('pc-template-name');
                    if (title) title.textContent = t.value;
                }
                // A radio fires both 'input' and 'change'; patch once, and
                // straight away - a unit switch is a click, not typing.
                if (t.name === 'unit') {
                    if (event.type === 'change') {
                        onCardPatch(t.closest('#pc-card-form'), true);
                    }
                    return;
                }
                debouncedCall(onCardPatch, t.closest('#pc-card-form'));
            }
            else if (t.id === 'pc-h-pos' || t.id === 'pc-v-pos') debouncedCall(onOffset);
            else if (t.closest('#pc-anchor')) onAnchor();
        }
        document.addEventListener('input', onFormEvent);
        document.addEventListener('change', onFormEvent);
    }

    function initAll() {
        const canvas = canvasEl();
        if (!canvas) return;
        bindControls();
        if (canvas.dataset.pcBound) return;
        // Opening a template always starts at 100% (not the last/fitted zoom).
        lastScale = 1;
        try { sessionStorage.removeItem('pc-scale-' + canvas.dataset.templateId); } catch (e) { /* ignore */ }
        initCanvas(canvas);
        updateHistoryButtons();
        settleCenter(canvas);
        selectItem(canvas, null, true); // start on the card panel
    }

    if (window.htmx) window.htmx.onLoad(function () { initAll(); });
    document.addEventListener('DOMContentLoaded', initAll);
})();
