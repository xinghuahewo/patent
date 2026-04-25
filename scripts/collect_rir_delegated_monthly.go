package main

import (
	"context"
	"crypto/sha256"
	"encoding/csv"
	"encoding/hex"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

const (
	defaultBaseURL = "https://ftp.ripe.net/pub/stats/ripencc/nro-stats"
	userAgent      = "asn-mismatch-pipeline/0.1 (+go monthly rir delegated snapshots)"
)

var sourceCandidates = []string{"nro-delegated-stats", "combined-stat"}

type job struct {
	Month        string
	SnapshotDate string
}

type result struct {
	Month        string
	SnapshotDate string
	SourceName   string
	SourceURL    string
	Path         string
	SHA256       string
	Bytes        int64
	LineCount    int64
	Status       string
	FetchedAt    string
	Err          error
}

func main() {
	var (
		months     = flag.Int("months", 60, "number of month-end snapshots to download")
		endMonth   = flag.String("end-month", lastCompletedMonth(time.Now().UTC()), "inclusive end month in YYYY-MM")
		workers    = flag.Int("workers", 4, "number of concurrent downloads")
		outputDir  = flag.String("output-dir", "data/raw/registry/delegated_monthly_go", "output directory")
		timeoutSec = flag.Int("timeout-sec", 180, "per-request timeout in seconds")
		baseURL    = flag.String("base-url", defaultBaseURL, "NRO stats base URL")
	)
	flag.Parse()

	if *months <= 0 {
		fatalf("--months must be positive")
	}
	if *workers <= 0 {
		fatalf("--workers must be positive")
	}
	if err := os.MkdirAll(*outputDir, 0o755); err != nil {
		fatalf("create output dir: %v", err)
	}

	client := &http.Client{Timeout: time.Duration(*timeoutSec) * time.Second}
	jobs := make(chan job)
	results := make(chan result)

	var wg sync.WaitGroup
	for i := 0; i < *workers; i++ {
		wg.Add(1)
		go func(workerID int) {
			defer wg.Done()
			for item := range jobs {
				results <- downloadMonth(client, *baseURL, *outputDir, item)
			}
		}(i)
	}

	go func() {
		for _, month := range monthSequence(*endMonth, *months) {
			jobs <- job{Month: month, SnapshotDate: monthEndDate(month)}
		}
		close(jobs)
		wg.Wait()
		close(results)
	}()

	var rows []result
	var failed int
	for row := range results {
		rows = append(rows, row)
		if row.Err != nil {
			failed++
			fmt.Fprintf(os.Stderr, "[ERROR] %s %s: %v\n", row.Month, row.SnapshotDate, row.Err)
			continue
		}
		fmt.Printf("[%s] %s -> %s (%d bytes, %d lines)\n", row.Status, row.Month, row.Path, row.Bytes, row.LineCount)
	}

	sort.Slice(rows, func(i, j int) bool {
		return rows[i].Month < rows[j].Month
	})
	if err := writeIndex(filepath.Join(*outputDir, "index.csv"), rows); err != nil {
		fatalf("write index: %v", err)
	}
	fmt.Printf("saved %d monthly delegated snapshots; failed=%d; index=%s\n", len(rows)-failed, failed, filepath.Join(*outputDir, "index.csv"))
	if failed > 0 {
		os.Exit(1)
	}
}

func downloadMonth(client *http.Client, baseURL, outputDir string, item job) result {
	finalPath := filepath.Join(outputDir, fmt.Sprintf("nro_delegated_stats_%s_%s.txt", item.Month, item.SnapshotDate))
	now := time.Now().UTC().Format(time.RFC3339)

	if info, err := os.Stat(finalPath); err == nil {
		sha, err := sha256File(finalPath)
		if err != nil {
			return result{Month: item.Month, SnapshotDate: item.SnapshotDate, Err: err, FetchedAt: now}
		}
		lines, err := countLines(finalPath)
		if err != nil {
			return result{Month: item.Month, SnapshotDate: item.SnapshotDate, Err: err, FetchedAt: now}
		}
		return result{
			Month: item.Month, SnapshotDate: item.SnapshotDate, Path: finalPath, SHA256: sha,
			Bytes: info.Size(), LineCount: lines, Status: "skipped_existing", FetchedAt: now,
		}
	}

	var lastErr error
	for _, sourceName := range sourceCandidates {
		url := strings.TrimRight(baseURL, "/") + "/" + item.SnapshotDate + "/" + sourceName
		tmpPath := finalPath + ".tmp"
		if err := fetchURL(client, url, tmpPath); err != nil {
			_ = os.Remove(tmpPath)
			lastErr = fmt.Errorf("%s: %w", sourceName, err)
			continue
		}
		lines, err := countLines(tmpPath)
		if err != nil {
			_ = os.Remove(tmpPath)
			return result{Month: item.Month, SnapshotDate: item.SnapshotDate, SourceName: sourceName, SourceURL: url, Err: err, FetchedAt: now}
		}
		if err := os.Rename(tmpPath, finalPath); err != nil {
			_ = os.Remove(tmpPath)
			return result{Month: item.Month, SnapshotDate: item.SnapshotDate, SourceName: sourceName, SourceURL: url, Err: err, FetchedAt: now}
		}
		sha, err := sha256File(finalPath)
		if err != nil {
			return result{Month: item.Month, SnapshotDate: item.SnapshotDate, SourceName: sourceName, SourceURL: url, Err: err, FetchedAt: now}
		}
		info, err := os.Stat(finalPath)
		if err != nil {
			return result{Month: item.Month, SnapshotDate: item.SnapshotDate, SourceName: sourceName, SourceURL: url, Err: err, FetchedAt: now}
		}
		return result{
			Month: item.Month, SnapshotDate: item.SnapshotDate, SourceName: sourceName, SourceURL: url,
			Path: finalPath, SHA256: sha, Bytes: info.Size(), LineCount: lines, Status: "ok", FetchedAt: now,
		}
	}

	return result{Month: item.Month, SnapshotDate: item.SnapshotDate, Err: lastErr, FetchedAt: now}
}

func fetchURL(client *http.Client, url, path string) error {
	ctx, cancel := context.WithTimeout(context.Background(), client.Timeout)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return err
	}
	req.Header.Set("User-Agent", userAgent)

	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("HTTP %d", resp.StatusCode)
	}

	out, err := os.Create(path)
	if err != nil {
		return err
	}
	defer out.Close()

	if _, err := io.CopyBuffer(out, resp.Body, make([]byte, 1024*1024)); err != nil {
		return err
	}
	return out.Sync()
}

func writeIndex(path string, rows []result) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()

	w := csv.NewWriter(f)
	defer w.Flush()
	header := []string{"month", "snapshot_date", "source_name", "source_url", "raw_evidence_path", "raw_evidence_sha256", "bytes", "line_count", "status", "fetched_at", "error"}
	if err := w.Write(header); err != nil {
		return err
	}
	for _, row := range rows {
		errText := ""
		if row.Err != nil {
			errText = row.Err.Error()
		}
		if err := w.Write([]string{
			row.Month,
			row.SnapshotDate,
			row.SourceName,
			row.SourceURL,
			row.Path,
			row.SHA256,
			fmt.Sprintf("%d", row.Bytes),
			fmt.Sprintf("%d", row.LineCount),
			row.Status,
			row.FetchedAt,
			errText,
		}); err != nil {
			return err
		}
	}
	return w.Error()
}

func sha256File(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()

	h := sha256.New()
	if _, err := io.CopyBuffer(h, f, make([]byte, 1024*1024)); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func countLines(path string) (int64, error) {
	f, err := os.Open(path)
	if err != nil {
		return 0, err
	}
	defer f.Close()

	var count int64
	buf := make([]byte, 1024*1024)
	for {
		n, err := f.Read(buf)
		for _, b := range buf[:n] {
			if b == '\n' {
				count++
			}
		}
		if err == io.EOF {
			break
		}
		if err != nil {
			return 0, err
		}
	}
	return count, nil
}

func lastCompletedMonth(now time.Time) string {
	year, month, _ := now.Date()
	month--
	if month == 0 {
		year--
		month = 12
	}
	return fmt.Sprintf("%04d-%02d", year, month)
}

func monthSequence(endMonth string, count int) []string {
	parts := strings.Split(endMonth, "-")
	if len(parts) != 2 {
		fatalf("invalid --end-month %q", endMonth)
	}
	var year, month int
	if _, err := fmt.Sscanf(endMonth, "%04d-%02d", &year, &month); err != nil || month < 1 || month > 12 {
		fatalf("invalid --end-month %q", endMonth)
	}

	months := make([]string, 0, count)
	for i := 0; i < count; i++ {
		months = append(months, fmt.Sprintf("%04d-%02d", year, month))
		month--
		if month == 0 {
			year--
			month = 12
		}
	}
	for i, j := 0, len(months)-1; i < j; i, j = i+1, j-1 {
		months[i], months[j] = months[j], months[i]
	}
	return months
}

func monthEndDate(month string) string {
	var year, monthNum int
	if _, err := fmt.Sscanf(month, "%04d-%02d", &year, &monthNum); err != nil {
		fatalf("invalid month %q", month)
	}
	lastDay := 31
	switch monthNum {
	case 4, 6, 9, 11:
		lastDay = 30
	case 2:
		lastDay = 28
		if year%400 == 0 || (year%4 == 0 && year%100 != 0) {
			lastDay = 29
		}
	}
	return fmt.Sprintf("%04d%02d%02d", year, monthNum, lastDay)
}

func fatalf(format string, args ...any) {
	fmt.Fprintf(os.Stderr, format+"\n", args...)
	os.Exit(1)
}
