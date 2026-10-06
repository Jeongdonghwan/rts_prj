// 스크롤 등장 효과, 숫자 카운트업, 헤더 그림자. JS가 꺼져 있어도 내용은 그대로 보임
const gnb = document.querySelector('.gnb');
addEventListener('scroll', () => gnb.classList.toggle('scrolled', scrollY > 40), { passive: true });

if (!matchMedia('(prefers-reduced-motion: reduce)').matches && 'IntersectionObserver' in window) {
  const countUp = el => {
    const end = +el.dataset.count, t0 = performance.now();
    const tick = t => {
      const p = Math.min((t - t0) / 1400, 1);
      el.textContent = Math.round(end * (1 - Math.pow(1 - p, 3))).toLocaleString();
      if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  };
  const io = new IntersectionObserver(entries => entries.forEach(e => {
    if (!e.isIntersecting) return;
    io.unobserve(e.target);
    e.target.classList.add('in');
    e.target.querySelectorAll('strong[data-count]').forEach(countUp);
  }), { threshold: 0.15 });
  document.querySelectorAll('.head, .stats div, .cards > *, .lines > *, .duo > *, .process li, .rows > div, .faq details, .split > *, .quote > *, .bleed > div, .form')
    .forEach(el => {
      el.classList.add('reveal');
      el.style.setProperty('--d', [...el.parentNode.children].indexOf(el) % 6 * 100 + 'ms');
      io.observe(el);
    });
}
