// Scroll Reveal Animation
const revealElements = document.querySelectorAll('.reveal');

const scrollReveal = () => {
    revealElements.forEach(element => {
        const elementTop = element.getBoundingClientRect().top;
        const windowHeight = window.innerHeight;
        
        if (elementTop < windowHeight - 100) {
            element.classList.add('active');
        }
    });
};

// Initial check on load
window.addEventListener('load', scrollReveal);
// Check on scroll
window.addEventListener('scroll', scrollReveal);

// FAQ Accordion
const faqItems = document.querySelectorAll('.faq-item');

faqItems.forEach(item => {
    const question = item.querySelector('.faq-question');
    const answer = item.querySelector('.faq-answer');
    const icon = item.querySelector('[data-lucide="chevron-down"]');

    question.addEventListener('click', () => {
        const isOpen = answer.style.display === 'block';
        
        // Close all other items
        faqItems.forEach(otherItem => {
            otherItem.querySelector('.faq-answer').style.display = 'none';
            const otherIcon = otherItem.querySelector('.faq-question i');
            if (otherIcon) otherIcon.style.transform = 'rotate(0deg)';
        });

        // Toggle current item
        if (!isOpen) {
            answer.style.display = 'block';
            const currentIcon = question.querySelector('i');
            if (currentIcon) currentIcon.style.transform = 'rotate(180deg)';
        }
    });
});

// Smooth scroll for navigation links
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        e.preventDefault();
        const targetId = this.getAttribute('href');
        if (targetId === '#') return;
        
        const target = document.querySelector(targetId);
        if (target) {
            window.scrollTo({
                top: target.offsetTop - 80,
                behavior: 'smooth'
            });
        }
    });
});

// Header scroll effect
const header = document.querySelector('header');
window.addEventListener('scroll', () => {
    if (window.scrollY > 50) {
        header.style.padding = '1rem 0';
        header.style.background = 'rgba(3, 7, 18, 0.9)';
    } else {
        header.style.padding = '1.5rem 0';
        header.style.background = 'rgba(3, 7, 18, 0.8)';
    }
});
