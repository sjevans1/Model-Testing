Test evidence

Command run from this directory:

    sh run_checks.sh

Output:

    PASS browser interaction, confirmation, loading/duplicate guard, failure, 409 conflict, accessibility, and 390px responsive layout
    run_checks.sh: done

The syntax checks were also run from this directory:

    node --check public/app.js && node --check tests/browser_test.mjs

Output: no output; exit status 0.

The browser test launches the mock API and Lightpanda locally, then drives the page over CDP. It verifies staging and discard do not write, explicit admin-grant and admin-removal confirmation, the loading/disabled state and duplicate-submit guard, distinct success/failure feedback, preserved pending state after HTTP 500 and 409, live-region/accessibility attributes, and the 390px responsive media rules and width/wrapping safeguards. Lightpanda's layout metrics are not reliable for a physical scroll-width assertion; the mobile check verifies the active compact CSS and its content-width constraints instead.
