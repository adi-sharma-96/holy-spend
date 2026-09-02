import type { DailySpend } from "./types";

export type CalendarDay = {
  date: string;
  day: number;
  amount: number;
  count: number;
  level: 0 | 1 | 2 | 3 | 4;
};

export type CalendarMonth = {
  year: number;
  month: number;
  label: string;
  total: number;
  count: number;
  leadingBlanks: number;
  days: CalendarDay[];
};

const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

function isoDate(year: number, month: number, day: number): string {
  return `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

/** Parses "YYYY-MM-DD" without timezone drift. Month is zero-based. */
export function parseIsoDate(value: string): { year: number; month: number; day: number } {
  const [year = 0, month = 1, day = 1] = value.slice(0, 10).split("-").map(Number);
  return { year, month: month - 1, day };
}

export function shiftMonth(
  year: number,
  month: number,
  delta: number,
): { year: number; month: number } {
  const index = year * 12 + month + delta;
  return { year: Math.floor(index / 12), month: ((index % 12) + 12) % 12 };
}

/**
 * Builds a Monday-first month grid from daily confirmed spend. Intensity
 * levels are relative to the month's own busiest day so every month uses the
 * full scale.
 */
export function buildCalendarMonth(
  year: number,
  month: number,
  daily: DailySpend[] | undefined,
  currency: string,
): CalendarMonth {
  const byDay = new Map<number, { amount: number; count: number }>();
  for (const entry of daily || []) {
    if (entry.currency !== currency) continue;
    const parsed = parseIsoDate(entry.spend_date);
    if (parsed.year !== year || parsed.month !== month) continue;
    const amount = Number(entry.amount);
    if (!Number.isFinite(amount)) continue;
    const existing = byDay.get(parsed.day) || { amount: 0, count: 0 };
    byDay.set(parsed.day, {
      amount: existing.amount + amount,
      count: existing.count + entry.transaction_count,
    });
  }
  const maximum = Math.max(...[...byDay.values()].map((entry) => entry.amount), 0);
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const leadingBlanks = (new Date(year, month, 1).getDay() + 6) % 7;
  const days: CalendarDay[] = [];
  let total = 0;
  let count = 0;
  for (let day = 1; day <= daysInMonth; day += 1) {
    const entry = byDay.get(day);
    const amount = entry?.amount || 0;
    total += amount;
    count += entry?.count || 0;
    const level =
      amount <= 0 || maximum <= 0
        ? 0
        : (Math.min(4, Math.max(1, Math.ceil((amount / maximum) * 4))) as 1 | 2 | 3 | 4);
    days.push({
      date: isoDate(year, month, day),
      day,
      amount,
      count: entry?.count || 0,
      level,
    });
  }
  return {
    year,
    month,
    label: `${MONTH_NAMES[month]} ${year}`,
    total,
    count,
    leadingBlanks,
    days,
  };
}

export function busiestDay(calendar: CalendarMonth): CalendarDay | undefined {
  return calendar.days.reduce<CalendarDay | undefined>(
    (best, day) => (day.amount > (best?.amount || 0) ? day : best),
    undefined,
  );
}
