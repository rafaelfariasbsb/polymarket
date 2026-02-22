"""Session statistics calculation and display."""

from __future__ import annotations

from colors import G, R, C, W, B, D, X


def calculate_session_stats(trade_history):
    """Calculate session statistics from trade history.

    Returns dict with: wins, losses, win_rate, best, worst,
    gross_wins, gross_losses, profit_factor, max_drawdown.
    """
    if not trade_history:
        return {
            'wins': 0, 'losses': 0, 'win_rate': 0, 'best': 0, 'worst': 0,
            'gross_wins': 0, 'gross_losses': 0, 'profit_factor': 0, 'max_drawdown': 0,
        }
    wins = sum(1 for t in trade_history if t > 0)
    losses = sum(1 for t in trade_history if t <= 0)
    win_rate = (wins / len(trade_history) * 100) if trade_history else 0
    best = max(trade_history)
    worst = min(trade_history)
    gross_wins = sum(t for t in trade_history if t > 0)
    gross_losses = abs(sum(t for t in trade_history if t < 0))
    profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else gross_wins
    # Max drawdown
    max_dd = 0.0
    peak = 0.0
    cumul = 0.0
    for t in trade_history:
        cumul += t
        if cumul > peak:
            peak = cumul
        dd = peak - cumul
        if dd > max_dd:
            max_dd = dd
    return {
        'wins': wins, 'losses': losses, 'win_rate': win_rate,
        'best': best, 'worst': worst,
        'gross_wins': gross_wins, 'gross_losses': gross_losses,
        'profit_factor': profit_factor, 'max_drawdown': max_dd,
    }


def print_session_summary(duration_min, trade_count, session_pnl, trade_history):
    """Print formatted session summary to terminal."""
    stats = calculate_session_stats(trade_history)
    print()
    print(f" {C}{B}{'═' * 45}{X}")
    print(f" {C}{B} SESSION SUMMARY{X}")
    print(f" {D}{'─' * 45}{X}")
    print(f"  Duration:       {duration_min:.0f} min")
    print(f"  Total Trades:   {trade_count}")
    if trade_history:
        wr_color = G if stats['win_rate'] >= 50 else R
        print(f"  Win Rate:       {wr_color}{stats['win_rate']:.0f}%{X} ({G}{stats['wins']}W{X} / {R}{stats['losses']}L{X})")
        pnl_c = G if session_pnl >= 0 else R
        print(f"  Total P&L:      {pnl_c}{'+' if session_pnl >= 0 else ''}${session_pnl:.2f}{X}")
        print(f"  Best Trade:     {G}+${stats['best']:.2f}{X}")
        print(f"  Worst Trade:    {R}${stats['worst']:.2f}{X}")
        print(f"  Profit Factor:  {W}{stats['profit_factor']:.2f}{X}")
        print(f"  Max Drawdown:   {R}-${stats['max_drawdown']:.2f}{X}")
    else:
        print(f"  {D}No trades this session{X}")
    print(f" {C}{B}{'═' * 45}{X}")
    print()
    return stats
