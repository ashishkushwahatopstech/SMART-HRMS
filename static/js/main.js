// Smart HRMS - Main Interactive & Responsive Controller
document.addEventListener('DOMContentLoaded', function () {
    // 1. Sidebar Controller (Desktop Collapsed Mini-Mode & Mobile Drawer)
    const sidebarToggleBtn = document.getElementById('sidebarToggle');
    const sidebarCloseBtn = document.getElementById('sidebarClose');
    const sidebar = document.getElementById('appSidebar');
    const backdrop = document.getElementById('sidebarBackdrop');

    // Automatically assign title attribute on links for native hover tooltips when collapsed
    if (sidebar) {
        sidebar.querySelectorAll('.sidebar-link').forEach(function (link) {
            const textSpan = link.querySelector('span');
            if (textSpan && !link.getAttribute('title')) {
                link.setAttribute('title', textSpan.textContent.trim());
            }
        });
    }

    function isDesktop() {
        return window.innerWidth >= 992;
    }

    function openMobileSidebar() {
        if (sidebar) sidebar.classList.add('show');
        if (backdrop) backdrop.classList.add('show');
        document.body.style.overflow = 'hidden';
    }

    function closeMobileSidebar() {
        if (sidebar) sidebar.classList.remove('show');
        if (backdrop) backdrop.classList.remove('show');
        document.body.style.overflow = '';
    }

    // Default State on Desktop: Sidebar is ALWAYS OPEN by default.
    // Respects session state if user actively toggles it.
    if (sidebar && isDesktop()) {
        const savedCollapsed = sessionStorage.getItem('sidebar_collapsed');
        if (savedCollapsed === 'true') {
            sidebar.classList.add('collapsed');
        } else {
            sidebar.classList.remove('collapsed');
        }
    }

    if (sidebarToggleBtn) {
        sidebarToggleBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            if (isDesktop()) {
                // Desktop: Toggle collapsed mini-sidebar mode
                if (sidebar) {
                    sidebar.classList.toggle('collapsed');
                    const isCollapsed = sidebar.classList.contains('collapsed');
                    sessionStorage.setItem('sidebar_collapsed', isCollapsed ? 'true' : 'false');
                }
            } else {
                // Mobile: Toggle offcanvas drawer
                if (sidebar && sidebar.classList.contains('show')) {
                    closeMobileSidebar();
                } else {
                    openMobileSidebar();
                }
            }
        });
    }

    if (sidebarCloseBtn) {
        sidebarCloseBtn.addEventListener('click', closeMobileSidebar);
    }

    if (backdrop) {
        backdrop.addEventListener('click', closeMobileSidebar);
    }

    // Auto close sidebar on mobile when navigating links
    if (sidebar) {
        sidebar.querySelectorAll('.sidebar-link').forEach(function (link) {
            link.addEventListener('click', function () {
                if (!isDesktop()) {
                    closeMobileSidebar();
                }
            });
        });
    }

    // Close on Escape key
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && sidebar) {
            if (!isDesktop() && sidebar.classList.contains('show')) {
                closeMobileSidebar();
            }
        }
    });

    // Handle window resize cleanly
    window.addEventListener('resize', function () {
        if (isDesktop()) {
            closeMobileSidebar();
            const savedCollapsed = sessionStorage.getItem('sidebar_collapsed');
            if (savedCollapsed === 'true' && sidebar) {
                sidebar.classList.add('collapsed');
            } else if (sidebar) {
                sidebar.classList.remove('collapsed');
            }
        } else {
            if (sidebar) sidebar.classList.remove('collapsed');
        }
    });

    // 2. Active Sidebar Link Detection & Distinct Highlighting
    function updateActiveSidebarLink() {
        if (!sidebar) return;

        const currentPath = window.location.pathname;
        const currentSearch = window.location.search;
        const links = Array.from(sidebar.querySelectorAll('.sidebar-link'));

        // Clear active state from all links first
        links.forEach(function (link) {
            link.classList.remove('active');
        });

        let bestMatch = null;
        let highestScore = -1;

        links.forEach(function (link) {
            const href = link.getAttribute('href');
            if (!href || href === '#' || href.startsWith('javascript:')) return;

            try {
                const url = new URL(href, window.location.origin);
                const linkPath = url.pathname;
                const linkSearch = url.search;

                let score = 0;

                // 1. Exact path + exact query match (e.g. /attendance/my/?punch=camera)
                if (linkSearch && currentPath === linkPath && currentSearch.includes(linkSearch.substring(1))) {
                    score = 1000 + linkPath.length;
                }
                // 2. Exact path match without query
                else if (!linkSearch && currentPath === linkPath) {
                    score = 500 + linkPath.length;
                }
                // 3. Home/Dashboard exact match only (avoid '/' matching everything)
                else if (linkPath === '/' || linkPath === '/dashboard/') {
                    if (currentPath === '/' || currentPath === '/dashboard/') {
                        score = 200;
                    }
                }
                // 4. Sub-path / Prefix match for deeper pages in the same module
                else if (linkPath.length > 1 && currentPath.startsWith(linkPath)) {
                    score = 100 + linkPath.length;
                }

                if (score > highestScore) {
                    highestScore = score;
                    bestMatch = link;
                }
            } catch (err) {
                // Ignore any malformed URLs
            }
        });

        if (bestMatch && highestScore > 0) {
            bestMatch.classList.add('active');
        }
    }

    // Run active link detection on page load
    updateActiveSidebarLink();

    // 2. Real-time digital clock in top navbar
    function updateClock() {
        const clockEl = document.getElementById('liveClock');
        if (clockEl) {
            const now = new Date();
            clockEl.textContent = now.toLocaleTimeString('en-US', {
                hour12: true,
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            });
        }
    }
    updateClock();
    setInterval(updateClock, 1000);

    // 3. Auto-dismiss alerts after 5 seconds with fade animation
    const alerts = document.querySelectorAll('.alert-dismissible');
    alerts.forEach(function (alert) {
        setTimeout(function () {
            try {
                if (window.bootstrap && bootstrap.Alert) {
                    const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
                    bsAlert.close();
                } else {
                    alert.style.transition = 'opacity 0.3s ease';
                    alert.style.opacity = '0';
                    setTimeout(function () { alert.remove(); }, 300);
                }
            } catch (e) {
                // Ignore
            }
        }, 5000);
    });

    // 4. One-click copy helper
    window.copyToClipboard = function (text, buttonEl) {
        if (!navigator.clipboard) {
            // Fallback for older browsers
            const input = document.createElement('input');
            input.value = text;
            document.body.appendChild(input);
            input.select();
            document.execCommand('copy');
            document.body.removeChild(input);
        } else {
            navigator.clipboard.writeText(text);
        }

        if (buttonEl) {
            const originalHtml = buttonEl.innerHTML;
            buttonEl.innerHTML = '<i class="bi bi-check2"></i> Copied!';
            buttonEl.classList.remove('btn-outline-secondary', 'btn-light');
            buttonEl.classList.add('btn-success');
            setTimeout(function () {
                buttonEl.innerHTML = originalHtml;
                buttonEl.classList.remove('btn-success');
                buttonEl.classList.add('btn-outline-secondary');
            }, 2000);
        }
    };
});
