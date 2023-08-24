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
	var xmlHttp = null;
	xmlHttp = new XMLHttpRequest();
	url = "{% url 'get-screen-last-update' event.id screen.id %}";
    if (screen_debug) { console.info('refresh_page_if_updated(url=[' + url + '])...'); }
	xmlHttp.open("GET", "{% url 'get-screen-last-update' event.id screen.id %}", false);
	xmlHttp.send(null);
	var response = xmlHttp.responseText;
	if (is_int(response)) {
		if (response > {{ now }}) {
		    if (screen_debug) { console.info('refresh_page_if_updated(): response=[' + response + '] > ' + {{ now }} + ' => refresh...'); }
			window.location = window.location;
		} else {
		    if (screen_debug) { console.info('refresh_page_if_updated(): response=[' + response + '] <= ' + {{ now }} + ' => no need to refresh.'); }
		}
	} else {
        if (screen_debug) { console.info('refresh_page_if_updated(): response=[' + response + '] is not valid :-('); }
	}
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
