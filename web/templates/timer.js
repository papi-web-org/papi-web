{% load mathfilters %}
{% with timer=event.timer %}
{% with color_1=timer.colors|get_item:1 color_2=timer.colors|get_item:2 color_3=timer.colors|get_item:3 %}
{% with color_1_r=color_1.0 color_1_g=color_1.1 color_1_b=color_1.2 %}
{% with color_2_r=color_2.0 color_2_g=color_2.1 color_2_b=color_2.2 %}
{% with color_3_r=color_3.0 color_3_g=color_3.1 color_3_b=color_3.2 %}
{% with delay_1=timer.delays|get_item:1 delay_2=timer.delays|get_item:2 delay_3=timer.delays|get_item:3 %}
var timer;
var timer_clock;
var timer_text;
function start_update_timer_interval() {
	timer = document.getElementById('timer');
	timer_clock = document.getElementById('timer-clock');
	timer_text = document.getElementById('timer-text');
	update_timer();
	setInterval('update_timer();', 1000);
}
function update_timer_values(clock_html, text_html, color) {
	if (timer_clock.innerHTML != clock_html) {
		timer_clock.innerHTML = clock_html;
	}
	if (timer.style.backgroundColor != color) {
		timer.style.backgroundColor = color;
	}
	if (timer_text.innerHTML != text_html) {
		timer_text.innerHTML = text_html;
	}
}
function two_digits(n) {
	return ('0' + n).slice(-2);
}
function duration(dur) {
	sec = dur % 60;
	sec_txt = sec + ' seconde' + (sec>1 ? 's' : '');
	dur = (dur - sec)/60;
	min = dur % 60;
	min_txt = min + ' minute' + (min>1 ? 's' : '');
	dur = (dur - min)/60;
	hou = dur % 24;
	hou_txt = hou + ' heure' + (hou>1 ? 's' : '');
	dur = (dur - hou)/24;
	day = dur % 7;
	day_txt = day + ' jour' + (day>1 ? 's' : '');
	wee = (dur - day)/7;
	wee_txt = wee + ' semaine' + (wee>1 ? 's' : '');
	if (wee > 0) { return wee_txt + (day > 0 ? ' et ' + day_txt : ''); }
	if (day > 0) { return day_txt + (hou > 0 ? ' et ' + hou_txt : ''); }
	if (hou > 0) { return hou_txt + (min > 0 ? ' et ' + min_txt : ''); }
	if (min > 0) { return min_txt + (sec > 0 ? ' et ' + sec_txt : ''); }
	return sec_txt;
}
function update_timer() {
	now = new Date();
	time = Math.floor(now.getTime() / 1000);
	clock_html = two_digits(now.getHours())+':'+two_digits(now.getMinutes())+':'+two_digits(now.getSeconds());
{% for hour in timer.hours %}
	if (time < {{ hour.timestamp_1 }}) { // {{ hour.datetime_str_1 }} color_1 {{ hour.text_before }}
		color = 'rgb({{ color_1_r }},{{ color_1_g }},{{ color_1_b }})';
		dur = duration({{ hour.timestamp }} - time);
		text_html = '{{ hour.text_before }}'.replace('%s', dur);
		update_timer_values(clock_html, text_html, color);
		return;
	}
	if (time < {{ hour.timestamp_2 }}) { // {{ hour.datetime_str_2 }} color_1 -> color_2 {{ hour.text_before }}
		color_r = Math.floor({{ color_1_r }} + (time - {{ hour.timestamp_1 }})/({{ delay_1|mul:60 }})*({{ color_2_r|sub:color_1_r }}));
		color_g = Math.floor({{ color_1_g }} + (time - {{ hour.timestamp_1 }})/({{ delay_1|mul:60 }})*({{ color_2_g|sub:color_1_g }}));
		color_b = Math.floor({{ color_1_b }} + (time - {{ hour.timestamp_1 }})/({{ delay_1|mul:60 }})*({{ color_2_b|sub:color_1_b }}));
		color = 'rgb(' + color_r + ',' + color_g + ',' + color_b + ')';
		dur = duration({{ hour.timestamp }} - time);
		text_html = '{{ hour.text_before }}'.replace('%s', dur);
		update_timer_values(clock_html, text_html, color);
		return;
	}
	if (time < {{ hour.timestamp_3 }}) { // {{ hour.datetime_str_3 }} color_2 -> color_3 {{ hour.text_before }}
		color_r = Math.floor({{ color_2_r }} + (time - {{ hour.timestamp_2 }})/({{ delay_2|mul:60 }})*({{ color_3_r|sub:color_2_r }}));
		color_g = Math.floor({{ color_2_g }} + (time - {{ hour.timestamp_2 }})/({{ delay_2|mul:60 }})*({{ color_3_g|sub:color_2_g }}));
		color_b = Math.floor({{ color_2_b }} + (time - {{ hour.timestamp_2 }})/({{ delay_2|mul:60 }})*({{ color_3_b|sub:color_2_b }}));
		color = 'rgb(' + color_r + ',' + color_g + ',' + color_b + ')';
		dur = duration({{ hour.timestamp }} - time);
		text_html = '{{ hour.text_before }}'.replace('%s', dur);
		update_timer_values(clock_html, text_html, color);
		return;
	}
	{% if not hour.last %}
	if (time < {{ hour.timestamp_next }}) { // {{ hour.datetime_str_next }} color_3 {{ hour.text_after }}
	{% endif %}
		color = 'rgb({{ color_3_r }},{{ color_3_g }},{{ color_3_b }})';
		dur = duration(time - {{ hour.timestamp }});
		text_html = '{{ hour.text_after }}'.replace('%s', dur);
		update_timer_values(clock_html, text_html, color);
		return;
	{% if not hour.last %}
	}
	{% endif %}
{% endfor %}
}
$(document).ready(function(){
    start_update_timer_interval();
});
{% endwith %}
{% endwith %}
{% endwith %}
{% endwith %}
{% endwith %}
{% endwith %}
