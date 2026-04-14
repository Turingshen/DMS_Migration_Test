"""
Test utilities for document migration module.
Provides helper functions for testing and debugging.
"""

import sys
import os
import pandas as pd
from sqlalchemy import text

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app_config import MiscEngine, DilEngine
from app.db_schema import init_staging_tables

misc_db = MiscEngine.load()
misc_engine = misc_db.engine

dil_db = DilEngine.load()
dil_engine = dil_db.engine


def create_test_batch_from_sample():
    """Create a test batch with sample data."""
    from app.prepare import prepare_migration, generate_batch_id, prepare_staging_records, save_to_staging
    
    print("Creating test batch with sample data...")
    
    # Sample test data
    sample_data = pd.DataFrame([
        {
            'Documentnumber': '0000000000000000000000001',
            'Documentpart': '000',
            'Documenttype': 'IY1',
            'Documentversion': '00',
            'Description': 'Test Document 1',
            'authorization_group': 'AUTH01'
        },
        {
            'Documentnumber': '0000000000000000000000002',
            'Documentpart': '000',
            'Documenttype': 'IY1',
            'Documentversion': '00',
            'Description': 'Test Document 2',
            'authorization_group': None
        }
    ])
    
    # Compute target numbers
    sample_data['target_documentnumber'] = sample_data['Documentnumber'].apply(
        lambda x: f"X55-{x.lstrip('0')}"
    )
    
    batch_id = generate_batch_id()
    staging_df = prepare_staging_records(sample_data, batch_id, 'test_sample')
    batch_id = save_to_staging(staging_df, batch_id, 'test_sample')
    
    print(f"✓ Test batch created: {batch_id}")
    print(f"  Records: {len(staging_df)}")
    return batch_id


def list_batches(limit=10):
    """List recent migration batches."""
    query = f"""
        SELECT TOP {limit}
            batch_id,
            created_at,
            created_by,
            source_file,
            total_records,
            approved_records,
            executed_records,
            successful_records,
            failed_records,
            status
        FROM dbo.migration_batch
        ORDER BY created_at DESC
    """
    
    with misc_engine.begin() as con:
        df = pd.read_sql(text(query), con)
    
    if len(df) == 0:
        print("No batches found")
        return None
    
    print("\nRecent Migration Batches:")
    print("=" * 120)
    print(df.to_string(index=False))
    print("=" * 120)
    return df


def get_batch_details(batch_id):
    """Get detailed information about a batch."""
    # Batch info
    batch_query = f"""
        SELECT * FROM dbo.migration_batch
        WHERE batch_id = '{batch_id}'
    """
    
    with misc_engine.begin() as con:
        batch_df = pd.read_sql(text(batch_query), con)
    
    if len(batch_df) == 0:
        print(f"Batch not found: {batch_id}")
        return None
    
    print(f"\nBatch Details: {batch_id}")
    print("=" * 80)
    for col in batch_df.columns:
        print(f"{col:25}: {batch_df[col].iloc[0]}")
    print("=" * 80)
    
    # Records summary
    records_query = f"""
        SELECT 
            validation_status,
            execution_status,
            COUNT(*) as count
        FROM dbo.migration_staging
        WHERE batch_id = '{batch_id}'
        GROUP BY validation_status, execution_status
        ORDER BY validation_status, execution_status
    """
    
    with misc_engine.begin() as con:
        records_df = pd.read_sql(text(records_query), con)
    
    print("\nRecords Summary:")
    print(records_df.to_string(index=False))
    print()
    
    return batch_df


def approve_all_in_batch(batch_id):
    """Approve all pending records in a batch (for testing)."""
    update_query = f"""
        UPDATE dbo.migration_staging
        SET user_approved = 1,
            validation_status = 'approved',
            validated_at = GETUTCDATE(),
            validated_by = 'test_script'
        WHERE batch_id = '{batch_id}'
            AND validation_status = 'pending'
    """
    
    with misc_engine.begin() as con:
        result = con.execute(update_query)
        count_query = f"""
            SELECT COUNT(*) as cnt FROM dbo.migration_staging
            WHERE batch_id = '{batch_id}' AND user_approved = 1
        """
        count_result = con.execute(count_query).fetchone()
        approved_count = count_result[0]
        
        con.execute(f"""
            UPDATE dbo.migration_batch
            SET approved_records = {approved_count}
            WHERE batch_id = '{batch_id}'
        """)
    
    print(f"✓ Approved {approved_count} records in batch {batch_id}")
    return approved_count


def view_failed_records(batch_id):
    """View failed records with error details."""
    query = f"""
        SELECT 
            id,
            source_documentnumber,
            target_documentnumber,
            execution_status,
            execution_error
        FROM dbo.migration_staging
        WHERE batch_id = '{batch_id}'
            AND execution_status IN ('failed', 'partial')
        ORDER BY id
    """
    
    with misc_engine.begin() as con:
        df = pd.read_sql(text(query), con)
    
    if len(df) == 0:
        print(f"No failed records in batch {batch_id}")
        return None
    
    print(f"\nFailed Records in Batch: {batch_id}")
    print("=" * 120)
    print(df.to_string(index=False))
    print("=" * 120)
    return df


def cleanup_test_batches():
    """Remove test batches (batches with source_file containing 'test')."""
    with misc_engine.begin() as con:
        # Find test batches
        test_query = """
            SELECT batch_id FROM dbo.migration_batch
            WHERE source_file LIKE '%test%'
        """
        test_df = pd.read_sql(text(test_query), con)
        
        if len(test_df) == 0:
            print("No test batches found")
            return 0
        
        batch_ids = "', '".join(test_df['batch_id'].tolist())
        
        # Delete staging records
        con.execute(f"""
            DELETE FROM dbo.migration_staging
            WHERE batch_id IN ('{batch_ids}')
        """)
        
        # Delete batches
        con.execute(f"""
            DELETE FROM dbo.migration_batch
            WHERE batch_id IN ('{batch_ids}')
        """)
        
        count = len(test_df)
        print(f"✓ Removed {count} test batches")
        return count


def reset_batch_for_retest(batch_id):
    """Reset a batch to allow re-execution (for testing)."""
    with misc_engine.begin() as con:
        # Reset execution status
        con.execute(f"""
            UPDATE dbo.migration_staging
            SET execution_status = 'pending',
                execution_started_at = NULL,
                execution_completed_at = NULL,
                execution_error = NULL
            WHERE batch_id = '{batch_id}'
        """)
        
        # Reset batch status
        con.execute(f"""
            UPDATE dbo.migration_batch
            SET status = 'prepared',
                executed_records = 0,
                successful_records = 0,
                failed_records = 0
            WHERE batch_id = '{batch_id}'
        """)
    
    print(f"✓ Reset batch {batch_id} for re-testing")


def check_database_setup():
    """Verify database tables exist and are accessible."""
    print("Checking database setup...")
    print()
    
    tables = ['migration_batch', 'migration_staging']
    all_ok = True
    
    for table in tables:
        try:
            query = f"SELECT COUNT(*) as cnt FROM dbo.{table}"
            with misc_engine.begin() as con:
                result = con.execute(query).fetchone()
                count = result[0]
            print(f"✓ Table {table:20} exists with {count:6} records")
        except Exception as e:
            print(f"✗ Table {table:20} ERROR: {e}")
            all_ok = False
    
    print()
    if all_ok:
        print("✓ Database setup is OK")
    else:
        print("✗ Database setup has issues - run init_db.py")
    
    return all_ok


# Interactive menu
def interactive_menu():
    """Interactive testing menu."""
    while True:
        print("\n" + "="*60)
        print("Document Migration - Test Utilities")
        print("="*60)
        print("1. Check database setup")
        print("2. List recent batches")
        print("3. Create test batch")
        print("4. View batch details")
        print("5. Approve all records in batch")
        print("6. View failed records")
        print("7. Reset batch for re-testing")
        print("8. Cleanup test batches")
        print("9. Exit")
        print("="*60)
        
        choice = input("\nEnter choice (1-9): ").strip()
        
        try:
            if choice == '1':
                check_database_setup()
            
            elif choice == '2':
                limit = input("How many batches to show? (default 10): ").strip()
                limit = int(limit) if limit else 10
                list_batches(limit)
            
            elif choice == '3':
                batch_id = create_test_batch_from_sample()
                print(f"\nNext steps:")
                print(f"1. Navigate to /validate?batch_id={batch_id}")
                print(f"2. Or use option 5 to approve all records")
            
            elif choice == '4':
                batch_id = input("Enter batch ID: ").strip()
                get_batch_details(batch_id)
            
            elif choice == '5':
                batch_id = input("Enter batch ID: ").strip()
                approve_all_in_batch(batch_id)
            
            elif choice == '6':
                batch_id = input("Enter batch ID: ").strip()
                view_failed_records(batch_id)
            
            elif choice == '7':
                batch_id = input("Enter batch ID: ").strip()
                reset_batch_for_retest(batch_id)
            
            elif choice == '8':
                confirm = input("Remove all test batches? (yes/no): ").strip().lower()
                if confirm == 'yes':
                    cleanup_test_batches()
            
            elif choice == '9':
                print("\nGoodbye!")
                break
            
            else:
                print("Invalid choice")
        
        except Exception as e:
            print(f"\nError: {e}")
            import traceback
            traceback.print_exc()
        
        input("\nPress Enter to continue...")


if __name__ == "__main__":
    try:
        interactive_menu()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(0)
