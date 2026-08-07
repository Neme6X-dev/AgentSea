function ouvrirMenu() {
  document.body.classList.toggle('menu-ouvert');
}
var bouton = document.querySelector('.brand');
bouton.onclick = ouvrirMenu;
