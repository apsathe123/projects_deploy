// MoneyVibe — vanilla JS

document.addEventListener('DOMContentLoaded', () => {
    // Score counter animation
    const counter = document.getElementById('score-counter');
    if (counter) {
        const target = parseInt(counter.dataset.target, 10);
        const duration = 1400;
        const start = performance.now();

        // Respect reduced motion
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
            counter.textContent = target;
        } else {
            function animate(now) {
                const elapsed = now - start;
                const progress = Math.min(elapsed / duration, 1);
                // ease-out cubic
                const eased = 1 - Math.pow(1 - progress, 3);
                counter.textContent = Math.round(target * eased);
                if (progress < 1) requestAnimationFrame(animate);
            }
            requestAnimationFrame(animate);
        }
    }

    // Live income/expense calculation on step_money
    const incomeEl = document.getElementById('monthly_income');
    const otherEl = document.getElementById('other_income');
    const expenseEl = document.getElementById('monthly_expenses');
    const totalIn = document.getElementById('total-in');
    const leftOver = document.getElementById('left-over');

    if (incomeEl && expenseEl && totalIn && leftOver) {
        function updateCalc() {
            const income = parseFloat(incomeEl.value) || 0;
            const other = parseFloat(otherEl?.value) || 0;
            const expenses = parseFloat(expenseEl.value) || 0;
            const total = income + other;
            const left = total - expenses;
            totalIn.textContent = '₹' + total.toLocaleString('en-IN');
            leftOver.textContent = '₹' + left.toLocaleString('en-IN');
            leftOver.style.color = left >= 0 ? 'var(--mv-mint)' : 'var(--mv-coral)';
        }
        incomeEl.addEventListener('input', updateCalc);
        if (otherEl) otherEl.addEventListener('input', updateCalc);
        expenseEl.addEventListener('input', updateCalc);
        updateCalc();
    }
});
