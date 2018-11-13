var current = '';

function select_changed(event) {
	var to_hide = '';
	if (event.target.value === 'errors') {
		to_hide = '.other_entry';
	} else if (event.target.value === 'others') {
		to_hide = '.err_entry';
	}
	var old = [];
	if (current !== '') {
		old = document.querySelectorAll(current);
	}
	var new_ones = [];
	if (to_hide !== '') {
		new_ones = document.querySelectorAll(to_hide);
	}

	for (var i = 0; i < old.length; i++) {
		old[i].classList.remove("hidden");
	}
	for (var i = 0; i < new_ones.length; i++) {
		new_ones[i].classList.add("hidden");
	}
	current = to_hide;
}

function show(id) {
	var elem = document.getElementById(id);
	if (elem === null) {
		return;
	}
	elem.classList.remove("to_hide");
}

function hide(id) {
	var elem = document.getElementById(id);
	if (elem === null) {
		return;
	}
	elem.classList.add("to_hide");
}

function replace_in(str, pat, new_pat) {
	return str.split(pat).join(new_pat);
}

function insert_after(newNode, referenceNode) {
	referenceNode.parentNode.insertBefore(newNode, referenceNode.nextSibling);
}

function load_more(id) {
	var elem = document.getElementById(id);
	if (elem === null || elem.childNodes[0].innerHTML !== 'Read more...') {
		return;
	}
	elem.childNodes[0].style.pointerEvents = 'none';
	elem.childNodes[0].innerHTML = '<img src="/spinner.gif" height="30" width="30">';
	var new_id = `${id}`.substr(1);

	var xhttp = new XMLHttpRequest();
	xhttp.onreadystatechange = function() {
		if (this.readyState != 4) {
			return;
		}
		elem.childNodes[0].style.pointerEvents = 'auto';
		elem.childNodes[0].innerHTML = 'Read more...';
		if (this.status === 200) {
			var new_elem = document.createElement("div");
			new_elem.classList = elem.classList;
			new_elem.id = `${id}-1`;
			new_elem.innerHTML = this.responseText;
			insert_after(new_elem, elem);
			elem.childNodes[0].attributes.onclick.value = `show('${id}-1');hide('${id}');`;
			hide(id);
		} else if (this.status === 401) {
			console.log('Invalid request...');
		} else if (this.status === 404) {
			console.log('Log does not exist anymore...');
		} else {
			console.log(`I do not know what happened: ${this.status}`);
		}
	};
	url = 'log/'+replace_in(replace_in(`${new_id}`, '/', ','), ' ', '_');
	xhttp.open("GET", url, true);
	xhttp.send();
}
