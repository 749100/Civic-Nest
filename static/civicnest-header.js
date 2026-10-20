(() => {
  const toggle = document.querySelector(".cn-menu-toggle");
  const drawer = document.querySelector(".cn-site-drawer");
  const backdrop = document.querySelector(".cn-drawer-backdrop");
  const closeButton = document.querySelector(".cn-drawer-close");

  if (!toggle || !drawer || !backdrop || !closeButton) {
    return;
  }

  const setOpen = (isOpen) => {
    document.documentElement.classList.toggle("cn-drawer-open", isOpen);
    document.body.classList.toggle("cn-drawer-open", isOpen);
    drawer.setAttribute("aria-hidden", String(!isOpen));
    drawer.inert = !isOpen;
    toggle.setAttribute("aria-expanded", String(isOpen));
    toggle.setAttribute(
      "aria-label",
      isOpen ? "Close site navigation" : "Open site navigation",
    );
    backdrop.hidden = !isOpen;

    if (isOpen) {
      closeButton.focus();
    } else {
      toggle.focus();
    }
  };

  toggle.addEventListener("click", () => {
    setOpen(toggle.getAttribute("aria-expanded") !== "true");
  });

  closeButton.addEventListener("click", () => setOpen(false));
  backdrop.addEventListener("click", () => setOpen(false));
  drawer.querySelectorAll("a").forEach((link) => {
    link.addEventListener("click", () => setOpen(false));
  });

  document.addEventListener("keydown", (event) => {
    if (toggle.getAttribute("aria-expanded") !== "true") {
      return;
    }

    if (event.key === "Escape") {
      setOpen(false);
      return;
    }

    if (event.key === "Tab") {
      const focusableItems = drawer.querySelectorAll(
        'a[href], button:not([disabled])',
      );
      const firstItem = focusableItems[0];
      const lastItem = focusableItems[focusableItems.length - 1];

      if (event.shiftKey && document.activeElement === firstItem) {
        event.preventDefault();
        lastItem.focus();
      } else if (!event.shiftKey && document.activeElement === lastItem) {
        event.preventDefault();
        firstItem.focus();
      }
    }
  });
})();
