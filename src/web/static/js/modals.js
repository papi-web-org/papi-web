let ignoreNextModalClose = false;
var modalForm;

function closeModal() {
    ignoreNextModalClose = false;
    var myModalEl = document.getElementById('modal-wrapper');
    var modal = bootstrap.Modal.getInstance(myModalEl);
    if (modal) {
        modal.hide();
    }
    closeTooltips();
    activateTooltips();
}

function isModalOpened() {
    return document.getElementById('modal-wrapper').classList.contains('show');
}

window.addEventListener('show.bs.modal', function(event) {
    var target = $(event.relatedTarget);
    if (!target) return;

    // After a modal closes, bootstrap refocuses the element causing the tooltip to reopen.
    // We disable the tooltip until the button loses focus.
    target.one("focus", function(event) {
        var parent = target.closest('*[data-bs-toggle="tooltip"]')
        if (parent) {
            parent.tooltip('disable');
            target.one('blur mouseover', function() {
                parent.tooltip('enable');
                target.blur();
                target.focus();
            })
        }

    })
});

function modalIsClosed() {
    return !document.getElementById('modal-wrapper').classList.contains('show');
}

var enterKeySubmitDisabled = false;

function handleModalOpened(static) {
    var modal = bootstrap.Modal.getOrCreateInstance('#modal-wrapper', {});

    // This is a hack to force the modal to be static
    // https://github.com/twbs/bootstrap/issues/35664
    // https://github.com/twbs/bootstrap/issues/35664#issuecomment-1028179994
    modal._config.backdrop = static ? 'static' : true;
    modal._config.keyboard = static ? false : true;

    if (modalIsClosed()) {
        // The modal is usually opened at this point, following a user action,
        // but this allows us to force open a modal from the server.
        modal.show();
    }

    modalForm = modal._element.querySelector("#modal-form");
    if (modalForm) {
        let eventListeners = $._data(modal._element, "events")
        if (!eventListeners || !eventListeners.keydown) { // avoid duplicate eventListeners
            $(modal._element).on("keydown", function(event) {
                if (event.key == "Enter") {
                    if (event.target.getAttribute("type") === "search") {
                        return;
                    }
                    if (!enterKeySubmitDisabled) {
                        event.preventDefault();
                        modalForm.dispatchEvent(new CustomEvent("enterKeypressFromModal"));
                        enterKeySubmitDisabled = true;
                        setTimeout(() => enterKeySubmitDisabled = false, 1000);
                    }
                }
            })
        }
    }

    closeTooltips();
    activateTooltips();
    if (!scrollToFirstError() && modalForm) {
        let fields = modalForm.getElementsByClassName("form-control");
        if (fields.length > 0) {
            // TODO: exclude filters from this
            fields[0].select(); // If the modal contains a form, set focus on the first field
        }
    }
}

window.addEventListener("modal_opened", function(event) {
    handleModalOpened(false);
});

window.addEventListener("static_modal_opened", function(event) {
    handleModalOpened(true);
});

window.addEventListener("close_modal", function(event) {
    closeModal()
});

var refreshRequested = false;

function requestRefresh() {
    refreshRequested = true;
}

// Intercept Bootstrap modal hide
$(document).on('hide.bs.modal', function (e) {
    if (ignoreNextModalClose) {
        e.stopImmediatePropagation();
        e.preventDefault();
        ignoreNextModalClose = false;
    } else if (refreshRequested) {
        e.preventDefault();
        window.dispatchEvent(new CustomEvent('request_refresh'));
        refreshRequested = false;
    }
});

last_url = '';

function preparePrintModal(print_document_id, tournament_id, print_round) {
    if (last_url !== window.location.href) {
        default_print_document_id = print_document_id || '';
        default_print_tournament_id = tournament_id || '';
        default_print_round = print_round || '';
        last_url = window.location.href;
    }
}

function triggerModalInitEvent(selector, event='change', params=[]) {
    // When a modal is swapped, the JS events are triggered on previous elements
    // Send the event again after the modal's been swapped to ensure triggering it on the correct element
    $(selector).trigger(event, params);
    setTimeout(() => $(selector).trigger(event, params), 100)
}
