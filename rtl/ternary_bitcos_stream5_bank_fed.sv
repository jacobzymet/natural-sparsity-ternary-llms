// Architecture B: direct bitmap/sign row engine fed from a 5-bit-wide
// presence memory and a byte-wide sign memory.
//
// Weight memories (outside this module, not synthesized): one synchronous
// read port each. <stream>_rd_en / <stream>_rd_addr are sampled at a clock
// edge; <stream>_rd_data is valid after that edge and holds until the next
// read of that memory. Filling the presence memory from a byte-packed bitmap
// uses the separate bitcos_presence_repack module, whose area and energy
// are included in the streamed Architecture B results.
// Each matrix row starts on a five-bit presence-word boundary. If its input
// width is not a multiple of five, zero-pad presence and activations in the
// last group. Padding consumes no sign bits; signs stay continuous across rows.
//
// Row protocol (identical to the other *_fed engines):
// - start pulses for one cycle with the word address of the row's first
//   presence word and the bit address of its first sign bit
// - PREFILL = 1 idle cycle follows
// - valid is then asserted for GROUPS consecutive cycles, last on the final
//   one; there are no stalls for any weight pattern
// - done pulses with dot one cycle after last
//
// Presence is fed like the five-trit stream: one word per group, read at the
// start edge and then on every valid edge, so the memory output is the
// current group's word and only an address counter is added. The sign stream
// is fed as in ternary_bitcos_stream5_fed: memory output = next byte, cur_sign
// = current byte, and fill moves the row's first byte into cur_sign during
// the prefill cycle.
module ternary_bitcos_stream5_bank_fed #(
    parameter int ACT_W = 8,
    parameter int ACC_W = 24,
    parameter int AW = 16
) (
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    start,
    input  logic [AW-1:0]           start_presence_addr,
    input  logic [AW+2:0]           start_sign_bit_addr,
    input  logic                    valid,
    input  logic                    last,
    input  logic [5*ACT_W-1:0]      activations,
    output logic                    presence_rd_en,
    output logic [AW-1:0]           presence_rd_addr,
    input  logic [4:0]              presence_rd_data,
    output logic                    sign_rd_en,
    output logic [AW-1:0]           sign_rd_addr,
    input  logic [7:0]              sign_rd_data,
    output logic signed [ACC_W-1:0] dot,
    output logic                    done
);
    logic fill;
    logic [7:0] cur_sign;
    logic [AW-1:0] presence_addr, sign_addr;
    logic advance_sign;
    logic [2:0] sign_offset;

    assign presence_rd_en = start | valid;
    assign presence_rd_addr = start ? start_presence_addr : presence_addr;
    assign sign_rd_en = start | fill | advance_sign;
    assign sign_rd_addr = start ? start_sign_bit_addr[AW+2:3] : sign_addr;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            fill <= 1'b0;
        else
            fill <= start;
    end

    always_ff @(posedge clk) begin
        if (presence_rd_en)
            presence_addr <= presence_rd_addr + 1'b1;
        if (sign_rd_en)
            sign_addr <= sign_rd_addr + 1'b1;
        if (fill | advance_sign)
            cur_sign <= sign_rd_data;
    end

    ternary_bitcos_stream5_directbank_accum #(
        .ACT_W(ACT_W),
        .ACC_W(ACC_W)
    ) engine (
        .clk(clk),
        .rst_n(rst_n),
        .start(start),
        .initial_sign_offset(start_sign_bit_addr[2:0]),
        .valid(valid),
        .last(last),
        .activations(activations),
        .presence(presence_rd_data),
        .current_sign_byte(cur_sign),
        .next_sign_byte(sign_rd_data),
        .advance_sign_byte(advance_sign),
        .sign_offset(sign_offset),
        .dot(dot),
        .done(done)
    );
endmodule
