# Device Compatibility Test Checklist

Test the app on a deliberately diverse set of devices before the UAT. The app must work on every phone a brother might bring — from a 2016 budget Android to a brand new iPhone.

## Required Test Devices

Borrow from family, friends, and council members to cover this range:

- [ ] Oldest iPhone available (ideally iPhone 6/7/8, iOS 12+)
- [ ] Newest iPhone available (iOS 17+)
- [ ] Oldest Android available (ideally Android 7-9)
- [ ] Newest Android available (Android 13+)
- [ ] Samsung phone using Samsung Internet browser
- [ ] iPad or Android tablet
- [ ] A laptop with Chrome
- [ ] A laptop with Firefox
- [ ] A laptop with Safari (if available)

## Per-Device Test Checklist

Run through this checklist for every device:

### Connection

- [ ] Connected to the the election WiFi successfully
- [ ] Reached the voting page (via captive portal OR by typing URL)

### Code Entry Page

- [ ] Can read all text without zooming
- [ ] Can tap the code field without difficulty
- [ ] Code field does not trigger autocorrect or autocomplete
- [ ] Code field does not zoom the page on iOS Safari
- [ ] Can enter a 6-character code without keyboard issues
- [ ] Pressing Enter submits the form
- [ ] Invalid code shows a clear error message above the input
- [ ] Error message is readable (large text, high contrast)

### Ballot Page

- [ ] Can see the full ballot without horizontal scrolling
- [ ] Can read all candidate names clearly
- [ ] Can tap each checkbox accurately on the first try
- [ ] Checkbox tap area is large enough (name + surrounding area)
- [ ] Can see which checkboxes are selected (clear visual change)
- [ ] "Select up to X" instruction is visible
- [ ] Can tap the "Cast Your Vote" button without difficulty
- [ ] Selecting too many candidates shows a server error and returns to ballot

### Confirmation Page

- [ ] Sees "Vote Recorded" confirmation
- [ ] "Next Voter" button is visible and tappable
- [ ] Page redirects to code entry after a few seconds
- [ ] Back button does not allow re-voting

### General

- [ ] No horizontal scrolling on any page
- [ ] No overlapping text or elements
- [ ] No broken images or missing styles
- [ ] App works with JavaScript disabled (test in browser settings)
- [ ] All pages load quickly (should be instant on local network)

## Browser-Specific Notes

### iOS Safari
- Input fields smaller than 16px font-size cause Safari to zoom in. Our inputs are 20px+.
- iOS Captive Network Assistant is a mini-browser with limited features. Test that the voting flow works in it.

### Samsung Internet
- May have its own autocomplete/autofill behaviour. Verify the code field doesn't trigger it.

### Android Chrome
- Older versions may not support some CSS features. Our CSS is deliberately conservative.

### Captive Portal Mini-Browsers
- These pop up when a phone joins WiFi with no internet. They are stripped-down browsers.
- The voting flow uses zero JavaScript, so it works in captive portal browsers.
- If the captive portal doesn't trigger, voters type the URL manually — test this path too.

## Issue Log

| Device | OS/Browser | Issue Found | Fixed? |
|--------|-----------|-------------|--------|
| | | | |
| | | | |
| | | | |
| | | | |

## Result

- [ ] **All devices passed** — the app is ready for the UAT
- [ ] **Issues found** — see log above, fix before UAT
