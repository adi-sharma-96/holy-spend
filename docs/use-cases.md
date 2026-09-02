# Use cases

Real screens, from real chats. Nothing staged.

## Forwarding a bill

Amazon, Uber Eats, Instacart, your gym, your internet bill, whatever. Forward
the email, it reads it, checks it against what you've bought before, and it's
tracked. No itemizing, no app.

<img src="screenshots/transaction-detail-email.png" width="260" alt="Transaction detail showing Email as the source, auto-confirmed by the scheduled ingestion task">

## Snapping a grocery receipt

Attach a photo or PDF and ask it to add and confirm. It checks your purchase
history before finalizing, then itemizes every line, priced per unit.

<table>
  <tr>
    <td align="center" width="50%">
      <img src="screenshots/chatgpt-receipt-add.png" width="260" alt="Attaching a receipt PDF in ChatGPT">
    </td>
    <td align="center" width="50%">
      <img src="screenshots/chatgpt-agent-trace.png" width="260" alt="ChatGPT's agent reasoning while confirming a receipt">
    </td>
  </tr>
</table>

## Catching a price change

Per-unit price on everything you buy more than once, flagged the moment it
moves, sale sticker or not.

<img src="screenshots/price-watch-inline.png" width="260" alt="Price Watch inline card">

## Tracking your own inflation

Not the national number. Your own basket, built only from things you buy
more than once, priced honestly against what they cost you before.

<img src="screenshots/my-inflation.png" width="260" alt="My Inflation, inside Price Watch">

## Grading your grocery basket

A to E, weighted by what you actually spend, so a cart of frozen pizza
doesn't score the same as a cart of vegetables just because they cost
the same.

<img src="screenshots/nutrition-inline.png" width="260" alt="Inline Nutrition card">

## The monthly check-in

Spend by category, six months as a bar chart, a calendar heatmap of the
month, and everything waiting on you to confirm, all without leaving chat.

<table>
  <tr>
    <td align="center" width="33%">
      <img src="screenshots/overview.png" width="200" alt="Overview card">
    </td>
    <td align="center" width="33%">
      <img src="screenshots/trends-inline.png" width="200" alt="Inline six-month trend card">
    </td>
    <td align="center" width="33%">
      <img src="screenshots/calendar-inline.png" width="200" alt="Inline spending calendar card">
    </td>
  </tr>
</table>

<img src="screenshots/transactions-inline.png" width="260" alt="Inline recent-transactions card">

---

Works the same from Claude, ChatGPT, Cursor, or anything else that speaks
MCP - same server, same data, no separate setup per client.
