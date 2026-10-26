const menuToggle = document.querySelector("#menu-toggle");
if (menuToggle) {
  menuToggle.addEventListener("click", () => {
    document.body.classList.toggle("menu-open");
  });
}
