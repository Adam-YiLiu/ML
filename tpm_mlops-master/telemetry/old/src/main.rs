use chrono::Utc;
use std::env;
use std::fs::{create_dir, OpenOptions};
use std::io::Write;
use std::path::PathBuf;
use sysinfo::System;
use tokio::time::{interval, Duration};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    const CAPTURE_FREQ: u64 = 10;
    let mut sys = System::new_all();
    let mut ticker = interval(Duration::from_millis(CAPTURE_FREQ));

    // create metrics directory in home directory
    let home_dir = env::var("HOME").unwrap_or_else(|_| ".".to_string());
    let metrics_dir = PathBuf::from(&home_dir).join("metrics");
    let _res = create_dir(&metrics_dir);

    let csv_filename = metrics_dir.join(format!(
        "system_metrics_{}.csv",
        Utc::now().format("%Y%m%d_%H%M%S")
    ));

    let mut file = OpenOptions::new()
        .create(true)
        .write(true)
        .append(true)
        .open(&csv_filename)?;

    // write CSV headers
    writeln!(
        file,
        "timestamp,cpu_usage_percent,memory_used_mb,memory_usage_percent"
    )?;

    // first refresh to get initial values
    sys.refresh_all();

    println!(
        "Monitoring system metrics every {}ms. Data saved to: {}",
        CAPTURE_FREQ,
        csv_filename.display()
    );

    loop {
        ticker.tick().await;

        sys.refresh_cpu_usage();
        sys.refresh_memory();

        // average CPU usage
        let cpu_usage: f32 =
            sys.cpus().iter().map(|cpu| cpu.cpu_usage()).sum::<f32>() / sys.cpus().len() as f32;

        // memory information
        let total_memory = sys.total_memory();
        let used_memory = sys.used_memory();
        let memory_usage_percent = (used_memory as f64 / total_memory as f64) * 100.0;

        let timestamp = Utc::now();

        // write to CSV
        // columns: timestamp,cpu_usage_percent,memory_used_mb,memory_usage_percent
        writeln!(
            file,
            "{},{:.2},{},{:.2}",
            timestamp.format("%Y-%m-%d %H:%M:%S%.3f"),
            cpu_usage,
            used_memory / 1024 / 1024, //  convert to MB
            memory_usage_percent,
        )?;

        // ensures data is written immediately
        file.flush()?;

        // println!(
        //     "{} - CPU: {:.2}%, Memory: {:.2}% ({} MB used)",
        //     timestamp.format("%H:%M:%S%.3f"),
        //     cpu_usage,
        //     memory_usage_percent,
        //     used_memory / 1024 / 1024,
        // );
    }
}
