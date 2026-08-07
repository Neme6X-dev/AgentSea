var params = new URLSearchParams(window.location.search);
var box = document.querySelector('.hero');
box.innerHTML = '<p>Bonjour ' + params.get('nom') + '</p>';
