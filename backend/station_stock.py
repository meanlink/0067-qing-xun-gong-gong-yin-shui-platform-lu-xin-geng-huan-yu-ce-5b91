def fleet(cx):
    return cx.execute('''
        SELECT s.*,e.expected,e.upper,e.history_week,
          (SELECT count(*) FROM service_weeks w WHERE w.station=s.code) AS samples
        FROM fountain_stations s LEFT JOIN replacement_estimates e ON e.station=s.code
        ORDER BY s.district,s.code
    ''').fetchall()
