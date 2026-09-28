// Five-trit row engine together with the hardware that feeds it from memory.
//
// Weight memory (outside this module, not synthesized): byte-wide, one
// synchronous read port. tace_rd_en / tace_rd_addr are sampled at a clock
// edge; tace_rd_data is valid after that edge and holds until the next read.
//
// Row protocol (identical to ternary_bitcos_stream5_fed):
// - start pulses for one cycle with start_tace_addr, the byte address of the
//   row's first group
// - PREFILL = 1 idle cycle follows (set by the direct engine, which needs it;
//   this engine works for any prefill length)
// - valid is then asserted for GROUPS consecutive cycles with five
//   activations each, and last on the final one
// - done pulses with dot one cycle after last, as in the bare engine
//
// Added state: only the byte address counter. The row's first byte is read at
// the start edge and the memory holds it through the prefill cycles; each
// valid cycle reads the byte for the following cycle. The memory output is
// the current group's byte, so it drives the decoder directly and no byte
// register is needed.
module ternary_five_trit_stream5_fed #(
    parameter int ACT_W = 8,
    parameter int ACC_W = 24,
    parameter int AW = 16
) (
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    start,
    input  logic [AW-1:0]           start_tace_addr,
    input  logic                    valid,
    input  logic                    last,
    input  logic [5*ACT_W-1:0]      activations,
    output logic                    tace_rd_en,
    output logic [AW-1:0]           tace_rd_addr,
    input  logic [7:0]              tace_rd_data,
    output logic signed [ACC_W-1:0] dot,
    output logic                    done
);
    logic [AW-1:0] tace_addr;

    assign tace_rd_en = start | valid;
    assign tace_rd_addr = start ? start_tace_addr : tace_addr;

    always_ff @(posedge clk) begin
        if (tace_rd_en)
            tace_addr <= tace_rd_addr + 1'b1;
    end

    ternary_five_trit_stream5_accum #(
        .ACT_W(ACT_W),
        .ACC_W(ACC_W)
    ) engine (
        .clk(clk),
        .rst_n(rst_n),
        .start(start),
        .valid(valid),
        .last(last),
        .activations(activations),
        .packed_weights(tace_rd_data),
        .dot(dot),
        .done(done)
    );
endmodule
