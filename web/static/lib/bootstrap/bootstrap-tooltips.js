tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]')
tooltipList = [...tooltipTriggerList].map(tooltipTriggerEl => new bootstrap.Tooltip(tooltipTriggerEl))
