var screen_debug = false;
if (screen_debug) {
    console.info('logging to console...');
}
$(document).ready(function(){
    $('#please-wait-modal').on('shown.bs.modal', function () {
        stop_refresh_interval();
    });
    $('#please-wait-modal').on('hidden.bs.modal', function () {
        start_refresh_interval();
    });
});
function please_wait() {
    $('#please-wait-modal').show();
}
function refresh() {
	please_wait();
	window.location = '';
}
function is_int(value) {
	var x;
	if (isNaN(value)) { return false; }
	x = parseFloat(value);
	return (x | 0) === x;
}
function refresh_page_if_updated() {
	var request = null;
	request = new XMLHttpRequest();
	url = "{% url 'get-screen-last-update' event.id screen.id %}";
    if (screen_debug) { console.info('refresh_page_if_updated(url=[' + url + '])...'); }
    $.ajax({
        url: url,
        type: "GET",
        success: function (data) {
            if (is_int(data)) {
                if (data > {{ now }}) {
                    if (screen_debug) {
                        console.info(
                            'refresh_page_if_updated():'
                            + ' response=[' + data + '] > ' + {{ now }}
                            + ' => refresh...'
                        );
                    }
                    window.location = window.location;
                } else {
                    if (screen_debug) {
                        console.info(
                            'refresh_page_if_updated():'
                            + ' response=[' + data + '] <= ' + {{ now }}
                            + ' => no need to refresh.'
                        );
                    }
                }
            } else {
                if (screen_debug) {
                    console.info(
                        'refresh_page_if_updated():'
                        + ' response=[' + data + '] is not valid :-('
                    );
                }
            }
        },
        error: function (jqXHR, exception) {
            console.log(
                'refresh_page_if_updated() failed:'
                + ' status_code=' + jqXHR.status +
                ', exception=' + exception,
                ', response=' + jqXHR.responseText
            );
        },
    });
}
var refresh_interval;
function start_refresh_interval() {
	refresh_page_if_updated();
	refresh_interval = setInterval("refresh_page_if_updated();", 10000);
}
function stop_refresh_interval() {
	clearInterval(refresh_interval);
	refresh_interval = 0;
}
$(document).ready(function(){
    $('.copyright').click(function () {
        refresh();
    });
    $('.timer').click(function () {
        refresh();
    });
    start_refresh_interval();
});
