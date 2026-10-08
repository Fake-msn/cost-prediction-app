// 首页交互逻辑
document.addEventListener('DOMContentLoaded', () => {
    // 平滑滚动
    document.querySelectorAll('a[href^="#"]').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const target = document.querySelector(link.getAttribute('href'));
            if (target) {
                target.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
            closeMobileNav();
        });
    });

    // 滚动监听：高亮当前所在区域的导航项
    const navLinks = document.querySelectorAll('.nav-links a[href^="#"]');
    const sections = Array.from(navLinks)
        .map(link => document.querySelector(link.getAttribute('href')))
        .filter(Boolean);

    function updateActiveNav() {
        const scrollY = window.scrollY + 100;
        let currentId = '';
        for (const section of sections) {
            if (section.offsetTop <= scrollY) {
                currentId = section.id;
            }
        }
        navLinks.forEach(link => {
            link.classList.toggle('active', link.getAttribute('href') === '#' + currentId);
        });
    }

    window.addEventListener('scroll', updateActiveNav, { passive: true });
    updateActiveNav();

    // 汉堡菜单
    const hamburgerBtn = document.getElementById('hamburger-btn');
    const mobileNav = document.getElementById('mobile-nav');

    if (hamburgerBtn && mobileNav) {
        hamburgerBtn.addEventListener('click', toggleMobileNav);
        mobileNav.addEventListener('click', (e) => {
            if (e.target === mobileNav) closeMobileNav();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closeMobileNav();
        });
    }

    function toggleMobileNav() {
        const isOpen = document.body.classList.toggle('mobile-nav-open');
        hamburgerBtn.setAttribute('aria-expanded', isOpen);
        hamburgerBtn.setAttribute('aria-label', isOpen ? '关闭导航菜单' : '打开导航菜单');
        document.body.style.overflow = isOpen ? 'hidden' : '';
    }

    function closeMobileNav() {
        document.body.classList.remove('mobile-nav-open');
        if (hamburgerBtn) {
            hamburgerBtn.setAttribute('aria-expanded', 'false');
            hamburgerBtn.setAttribute('aria-label', '打开导航菜单');
        }
        document.body.style.overflow = '';
    }
});
