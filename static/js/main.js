document.addEventListener('DOMContentLoaded', () => {
  const cards = document.querySelectorAll('.kpi-card, .feature-card, .card-soft, .form-card, .history-card, .admin-card');
  cards.forEach((card, index) => {
    card.style.opacity = '0';
    card.style.transform = 'translateY(24px)';
    card.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
    setTimeout(() => {
      card.style.opacity = '1';
      card.style.transform = 'translateY(0px)';
    }, index * 80);
  });
});
