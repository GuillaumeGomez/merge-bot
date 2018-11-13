var current = '';

function select_changed(v){
	var old = document.querySelectorAll(`.line_${current}`);
	var new_ones = document.querySelectorAll(`.line_${v.target.value}`);

	for (var i = 0; i < old.length; i++) {
		old[i].classList.remove("disp");
	}
	for (var i = 0; i < new_ones.length; i++) {
		new_ones[i].classList.add("disp");
	}
	current = v.target.value;
	if (current !== '') {
		window.history.pushState('S3', 'Build queue', '/queue/' + current);
	} else {
		window.history.pushState('S3', 'Build queue', '/queue');
	}
}

function display_deps(args) {
	for (var i = 0; i < args.length; i++) {
		args[i] = `<a href="${args[i]}" target="_blank">${args[i]}</a>`;
	}
	display_popup(args, 'Dependencies');
}

function display_env(args) {
	display_popup(args, 'Environment arguments');
}

function display_popup(args, title) {
	var el = document.getElementById('popup_header');
	if (el) {
		el.innerText = title;
	}
	el = document.getElementById('popup_content');
	if (el) {
		content = "";
		if (args.constructor === Array) {
			for (var i = 0; i < args.length; i++) {
				content += '<li>' + args[i] + '</li>';
			}
		} else {
			for (var key in args) {
				if (args.hasOwnProperty(key)) {
					content += '<li>' + key + ': ' + args[key] + '</li>';
				}
			}
		}
		if (content.length > 0) {
			el.innerHTML = "<ul>" + content + '</ul>';
		} else {
			el.innerHTML = "<p style='margin-top:13px;font-size:19px;'>Nothing to see here...</p>";
		}
	}
	el = document.getElementById('popup');
	if (el) {
		el.style = 'display: block;';
	}
}

function close_popup() {
	var el = document.getElementById('popup');
	if (el) {
		el.style = '';
	}
}

parts = window.location.pathname.split('/').filter(n => n.length > 0);
if (parts.length !== 1) {
	var elem = document.getElementById('repos');
	if (elem) {
		elem.value = parts[parts.length - 1];
		select_changed({target: elem});
	}
}
