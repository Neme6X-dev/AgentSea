/**
 * GRAND AZURE LUXURY RESORT - MAIN JAVASCRIPT & THEME SWITCHER
 */

document.addEventListener('DOMContentLoaded', () => {
  // 1. THEME SWITCHER SYSTEM (LIGHT / DARK MODE)
  const themeToggleBtn = document.getElementById('theme-toggle');
  
  // Get preferred or stored theme
  const storedTheme = localStorage.getItem('theme');
  const systemPrefersLight = window.matchMedia('(prefers-color-scheme: light)').matches;
  
  let currentTheme = storedTheme || (systemPrefersLight ? 'light' : 'dark');
  applyTheme(currentTheme);

  if (themeToggleBtn) {
    themeToggleBtn.addEventListener('click', () => {
      currentTheme = currentTheme === 'dark' ? 'light' : 'dark';
      applyTheme(currentTheme);
      localStorage.setItem('theme', currentTheme);
    });
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    if (themeToggleBtn) {
      const icon = themeToggleBtn.querySelector('i');
      if (icon) {
        if (theme === 'light') {
          icon.className = 'fa-solid fa-moon';
          themeToggleBtn.setAttribute('title', 'Passer en Mode Sombre');
        } else {
          icon.className = 'fa-solid fa-sun';
          themeToggleBtn.setAttribute('title', 'Passer en Mode Clair');
        }
      }
    }
  }

  // 2. HEADER SCROLL STATE
  const navbar = document.querySelector('.header-navbar');
  window.addEventListener('scroll', () => {
    if (window.scrollY > 40) {
      navbar.style.boxShadow = 'var(--shadow-soft)';
    } else {
      navbar.style.boxShadow = 'none';
    }
  });

  // 3. SCROLL REVEAL ANIMATIONS
  const animateElements = document.querySelectorAll('.animate-on-scroll');
  const observerOptions = {
    threshold: 0.15,
    rootMargin: '0px 0px -40px 0px'
  };

  const observer = new IntersectionObserver((entries, obs) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-visible');
        obs.unobserve(entry.target);
      }
    });
  }, observerOptions);

  animateElements.forEach(el => observer.observe(el));

  // 4. BOOKING SEARCH SIMULATOR
  const bookingForm = document.querySelector('.booking-search-bar');
  if (bookingForm) {
    bookingForm.addEventListener('submit', (e) => {
      e.preventDefault();
      const checkin = document.getElementById('checkin')?.value || 'Aujourd\'hui';
      const guests = document.getElementById('guests')?.value || '2 Invités';
      
      alert(`🔎 Recherche de disponibilités pour ${guests} à partir du ${checkin}. Redirection vers les meilleures offres !`);
    });
  }

  // 5. CONCIERGE FORM HANDLER
  const contactForm = document.querySelector('.contact-form');
  if (contactForm) {
    contactForm.addEventListener('submit', (e) => {
      e.preventDefault();
      const submitBtn = contactForm.querySelector('button[type="submit"]');
      const originalText = submitBtn.innerHTML;

      submitBtn.disabled = true;
      submitBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Confirmation en cours...';

      setTimeout(() => {
        submitBtn.innerHTML = '✓ Réservation / Demande transmise avec succès!';
        submitBtn.style.background = '#38a169';
        submitBtn.style.color = '#ffffff';

        setTimeout(() => {
          contactForm.reset();
          submitBtn.disabled = false;
          submitBtn.innerHTML = originalText;
          submitBtn.style.background = '';
          submitBtn.style.color = '';
        }, 3000);
      }, 1200);
    });
  }
});
